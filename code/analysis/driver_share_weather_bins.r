# ============================================================
# Script: driver_share_weather_bins.r
# Purpose: Binned regression of trip-level driver_share on origin (pickup hour) and
#          destination (dropoff hour) rainfall: current-hour bins and (spec "r6") bins of
#          trailing 6-hour rain (hours t-6..t-1). OD cells, weights = n_trips.
# Usage:   Rscript --vanilla code/analysis/driver_share_weather_bins.r [months] [tag] [spec]
#            months: comma list, e.g. "8" or "8,9" (default all 12)
#            tag:    output suffix (default "2021")
#            spec:   "cur" = current-hour bins only; "r6" (default) = current-hour + 6h bins
#            outcomes: "share" (default) or "decomp" (4 outcomes: driver_share, log_fare, log_pay,
#                    log_share = log_pay - log_fare; reads the v2 cells)
#            engine: "feols" (default; fixest::feols, kept for validation) or "fwl"
#                    (exact batched Frisch-Waugh-Lovell estimator, code/analysis/fwl_batched.r)
#          Run ONE model per R session (memory).
# Inputs: clean_data/od_weather_cells_2021/ (cells_2021-MM.parquet)
#         clean_data/rain6h_zone_hour_2021.parquet (spec r6; built by build_rain6h_lookup.py)
# Outputs: output/reg/driver_share_weather_bins_{tag}.tex (+ .rds)
#          output/fig/driver_share_weather_bins_{tag}.png
#          output/sum/driver_share_bin_counts_{tag}.csv
# Timezone: datetime_hour / do_datetime_hour are tz-aware America/New_York (the 6h join uses
#          these tz-aware stamps, so DST hours match true elapsed time); month, dow, pu_hod,
#          do_hod come from the local wall clock.
# Author: EK  Date: 2026-09-30
# ============================================================

suppressPackageStartupMessages({
  library(arrow); library(dplyr); library(fixest); library(ggplot2)
})
source("code/analysis/fhv_reg.r")  # wrap_for_beamer()
source("code/analysis/fwl_batched.r")  # fwl_fit(), fwl_etable_tex()

args <- commandArgs(trailingOnly = TRUE)
months <- if (length(args) >= 1 && nzchar(args[1])) as.integer(strsplit(args[1], ",")[[1]]) else 1:12
tag    <- if (length(args) >= 2) args[2] else "2021"
spec   <- if (length(args) >= 3) args[3] else "r6"
stopifnot(spec %in% c("cur", "r6"))
use_r6 <- spec == "r6"
engine <- if (length(args) >= 4) args[4] else "feols"
stopifnot(engine %in% c("feols", "fwl"))
# outcomes: "share" (default, driver_share only) or "decomp" = driver_share, log_fare, log_pay, log_share
# estimated on the v2 cells (clean_data/od_weather_cells_2021_v2, which add sum_log_fare / sum_log_pay).
outcomes <- if (length(args) >= 5) args[5] else "share"
stopifnot(outcomes %in% c("share", "decomp"))
decomp <- outcomes == "decomp"
# Development only: restrict pickup dates (e.g. Sys.setenv(DSW_MAX_DATE = "2021-08-05")) for quick tests.
max_date <- Sys.getenv("DSW_MAX_DATE", unset = "")

# ---- bin definitions ----------------------------------------------------
# Left-closed, mm. 0.1 rather than 0 as dry cutoff (area-weighted MRMS gives tiny positives).
# Labels contain no ")" (fixest/etable mangle them).
PRECIP_BREAKS <- c(0, 0.1, 0.25, 0.5, 1, 2, 4, 6, 10, 15, 25, 40, Inf)       # mm/h, current hour
PRECIP_LABELS <- c("dry", "0.1-0.25", "0.25-0.5", "0.5-1", "1-2", "2-4", "4-6", "6-10", "10-15", "15-25", "25-40", "ge40")
R6_BREAKS <- c(0, 0.1, 0.5, 1, 2, 5, 10, 20, 35, 50, 75, Inf)                # mm over t-6..t-1
R6_LABELS <- c("dry", "0.1-0.5", "0.5-1", "1-2", "2-5", "5-10", "10-20", "20-35", "35-50", "50-75", "ge75")
REF <- "dry"
# DO zone 265 (outside NYC) is kept (user decision 2026-09-30) with level "outside_nyc". It is
# exactly collinear with the do_zone x do_hod FE, and fixest does not drop it reliably (noise
# coefficient), so it is passed as a second reference level in i(): equivalent to absorbing it.
# These trips inform only the origin-rain coefficients.
OUTSIDE_NYC_ZONE  <- 265L
OUTSIDE_NYC_LABEL <- "outside_nyc"

# ---- load (Arrow; 6h join done before collect) ---------------------------
need <- c("platform", "pu_zone_id", "do_zone_id", "datetime_hour", "do_datetime_hour", "date",
          "month", "dow", "pu_hod", "do_hod", "n_trips", "sum_driver_share", "pu_precip_mm", "do_precip_mm", if (decomp) c("sum_log_fare", "sum_log_pay"))
cells_dir <- if (decomp) "clean_data/od_weather_cells_2021_v2" else "clean_data/od_weather_cells_2021"
ds <- open_dataset(file.path(cells_dir, sprintf("cells_2021-%02d.parquet", months))) |> filter(month %in% months)
if (nzchar(max_date)) ds <- ds |> filter(date <= as.Date(max_date))
ds <- ds |> select(all_of(need))
if (use_r6) {
  lk <- open_dataset("clean_data/rain6h_zone_hour_2021.parquet")
  lk_pu <- lk |> rename(pu_zone_id = zone_id, pu_rain6h_mm = rain6h_mm)
  lk_do <- lk |> rename(do_zone_id = zone_id, do_datetime_hour = datetime_hour, do_rain6h_mm = rain6h_mm)
  # tz-aware timestamps: spring-forward 02:xx pickups sit at 03:00 EDT and fall-back 01:00 at EST;
  # both exist in the lookup.
  ds <- ds |> left_join(lk_pu, by = c("pu_zone_id", "datetime_hour")) |>
              left_join(lk_do, by = c("do_zone_id", "do_datetime_hour"))
}
ph <- function(x) cat(format(Sys.time(), "%H:%M:%S"), "PHASE", x, "
")
ph("collect start"); df <- collect(ds); ph("collect done")
rm(ds); gc()
str(df)
stopifnot(identical(attr(df$datetime_hour, "tzone"), "America/New_York"),
          identical(attr(df$do_datetime_hour, "tzone"), "America/New_York"),
          is.integer(df$pu_zone_id), is.integer(df$do_zone_id))
df$datetime_hour <- NULL; df$do_datetime_hour <- NULL

# driver_share = cell mean of trip-level ratios; n_trips-weighted cell regression = trip-level OLS.
df$driver_share <- df$sum_driver_share / df$n_trips
df$sum_driver_share <- NULL
if (decomp) {
  # trip-level means of ln(fare), ln(pay); log_share = mean ln(pay/fare) = log_pay - log_fare exactly.
  df$log_fare <- df$sum_log_fare / df$n_trips
  df$log_pay <- df$sum_log_pay / df$n_trips
  df$log_share <- df$log_pay - df$log_fare
  df$sum_log_fare <- NULL; df$sum_log_pay <- NULL
}

# ---- NA handling and match rates ------------------------------------------
is_outside <- df$do_zone_id == OUTSIDE_NYC_ZONE
n_outside_trips <- sum(df$n_trips[is_outside]); n_outside_cells <- sum(is_outside)
bad <- is.na(df$pu_precip_mm) | (!is_outside & is.na(df$do_precip_mm))
if (use_r6) {
  na_pu6 <- is.na(df$pu_rain6h_mm); na_do6 <- !is_outside & is.na(df$do_rain6h_mm)
  sh_pu6 <- mean(na_pu6); sh_do6 <- mean(na_do6[!is_outside]) # destination share on in-NYC destinations
  cat(sprintf("6h match: NaN share pu_rain6h = %.3f%% ; do_rain6h (in-NYC dest.) = %.3f%% ; (expect ~0.6%%)\n", 100 * sh_pu6, 100 * sh_do6))
  stopifnot("6h NaN share > 2%: key/unit mismatch" = sh_pu6 <= 0.02 && sh_do6 <= 0.02)
  bad <- bad | na_pu6 | na_do6
  rm(na_pu6, na_do6)
}
n_cells_all <- nrow(df); n_trips_all <- sum(df$n_trips)
n_cells_na <- sum(bad); n_trips_na <- sum(df$n_trips[bad])
cat(sprintf("NA-weather cells dropped: %s of %s (%.3f%%); trips %s of %s\n",
            format(n_cells_na, big.mark = ","), format(n_cells_all, big.mark = ","), 100 * n_cells_na / n_cells_all,
            format(n_trips_na, big.mark = ","), format(n_trips_all, big.mark = ",")))
keep <- !bad
df <- df[keep, ]; is_outside <- is_outside[keep]; rm(keep, bad); gc()
cat(sprintf("DO-265 (outside NYC) kept: %s trips, %s cells\n", format(n_outside_trips, big.mark = ","), format(n_outside_cells, big.mark = ",")))

# ---- bin immediately, then trim -------------------------------------------
bin_with_outside <- function(x, br, lb) {
  b <- cut(x, br, labels = lb, right = FALSE)
  levels(b) <- c(levels(b), OUTSIDE_NYC_LABEL)
  b
}
df$pu_precip_bin <- cut(df$pu_precip_mm, PRECIP_BREAKS, labels = PRECIP_LABELS, right = FALSE)
df$do_precip_bin <- bin_with_outside(df$do_precip_mm, PRECIP_BREAKS, PRECIP_LABELS)
df$do_precip_bin[is_outside] <- OUTSIDE_NYC_LABEL
df$pu_precip_mm <- NULL; df$do_precip_mm <- NULL
if (use_r6) {
  df$pu_rain6h_bin <- cut(df$pu_rain6h_mm, R6_BREAKS, labels = R6_LABELS, right = FALSE)
  df$do_rain6h_bin <- bin_with_outside(df$do_rain6h_mm, R6_BREAKS, R6_LABELS)
  df$do_rain6h_bin[is_outside] <- OUTSIDE_NYC_LABEL
  df$pu_rain6h_mm <- NULL; df$do_rain6h_mm <- NULL
}
stopifnot(!anyNA(df$pu_precip_bin), !anyNA(df$do_precip_bin))
if (use_r6) stopifnot(!anyNA(df$pu_rain6h_bin), !anyNA(df$do_rain6h_bin))
# Trim (no effect on estimates): factor platform, integer date for clustering, single-column
# integer ids for the two zone x hour-of-day FEs (hod < 24, so id = zone*100 + hod is unique).
df$platform <- factor(df$platform)
df$date_int <- as.integer(df$date); df$date <- NULL
df$pu_fe <- df$pu_zone_id * 100L + as.integer(df$pu_hod)
df$do_fe <- df$do_zone_id * 100L + as.integer(df$do_hod)
df$pu_hod <- NULL; df$do_hod <- NULL; df$do_zone_id <- NULL
rm(is_outside); gc()

n_cells <- nrow(df); n_trips <- sum(df$n_trips)

ph("bins done")
# ---- bin counts -------------------------------------------------------------
bvars <- c("pu_precip_bin", "do_precip_bin", if (use_r6) c("pu_rain6h_bin", "do_rain6h_bin"))
bin_counts <- do.call(rbind, lapply(bvars, function(v) {
  d <- df |> group_by(bin = .data[[v]]) |> summarise(n_trips = sum(n_trips), n_cells = n(), n_days = n_distinct(date_int), .groups = "drop")
  data.frame(variable = v, bin = as.character(d$bin), n_trips = d$n_trips, n_cells = d$n_cells, n_days = d$n_days)
}))
write.csv(bin_counts, sprintf("output/sum/driver_share_bin_counts_%s.csv", tag), row.names = FALSE)

ph("estimate start")
# ---- estimate -----------------------------------------------------------
fe_txt  <- "platform + pu_fe + do_fe + month + dow"
rhs_cur <- 'i(pu_precip_bin, ref = "dry") + i(do_precip_bin, ref = c("dry", "outside_nyc"))'
rhs_r6  <- paste(rhs_cur, '+ i(pu_rain6h_bin, ref = "dry") + i(do_rain6h_bin, ref = c("dry", "outside_nyc"))')
ynames  <- if (decomp) c("driver_share", "log_fare", "log_pay", "log_share") else "driver_share"
lhs_txt <- if (decomp) paste0("c(", paste(ynames, collapse = ", "), ")") else "driver_share"
fml_bins <- as.formula(paste0(lhs_txt, " ~ ", if (use_r6) rhs_r6 else rhs_cur, " | ", fe_txt))
gc()
if (engine == "feols") {
  tm <- system.time(
    est <- feols(fml_bins, data = df, weights = ~n_trips, cluster = ~pu_zone_id + date_int,
                 lean = TRUE, mem.clean = TRUE, nthreads = 16)
  )
  est_list <- if (decomp) lapply(seq_along(ynames), function(k) est[[k]]) else list(est)
  names(est_list) <- ynames
  by_outcome <- lapply(est_list, function(e) {
    cts <- as.data.frame(coeftable(e)); cts$term <- rownames(cts)
    list(coeftable = cts, vcov = e$cov.scaled,
         fit_info = list(nobs = nobs(e), K = attr(e$cov.scaled, "df.K"), nparams = e$nparams,
                         fe_sizes = e$fixef_sizes, df_t = attr(e$cov.scaled, "df.t"),
                         r2 = unname(fixest::r2(e, "r2")), seconds = tm[["elapsed"]]))
  })
  cat(sprintf("feols elapsed: %.1f s (user %.1f, sys %.1f); N = %s; n coef = %d; outcomes = %s\n", tm[["elapsed"]], tm[["user.self"]], tm[["sys.self"]],
              format(by_outcome[[1]]$fit_info$nobs, big.mark = ","), nrow(by_outcome[[1]]$coeftable), paste(ynames, collapse = ",")))
  fit_info <- by_outcome[[1]]$fit_info
  ct <- by_outcome[[1]]$coeftable
  vcov_mat <- by_outcome[[1]]$vcov
  cat(sprintf("feols: K = %s (nparams %s), df.t = %s, R2 = %.6f\n", fit_info$K, fit_info$nparams, fit_info$df_t, fit_info$r2))
  est <- est_list[[1]]
} else {
  fwl_env <- new.env()
  fwl_env$y <- if (decomp) setNames(lapply(ynames, function(v) df[[v]]), ynames) else df$driver_share
  fwl_env$w <- df$n_trips
  fwl_env$bins <- df[, bvars]
  fwl_env$fe <- list(platform = as.integer(df$platform), pu_fe = df$pu_fe, do_fe = df$do_fe, month = as.integer(df$month), dow = as.integer(df$dow))
  fwl_env$cl <- list(pu_zone_id = df$pu_zone_id, date_int = df$date_int)
  fwl_refs <- setNames(lapply(bvars, function(b) if (startsWith(b, "do_")) c("dry", OUTSIDE_NYC_LABEL) else "dry"), bvars)
  rm(df); gc()   # free the data frame before the FWL fit (fwl_fit consumes fwl_env)
  tm_fit <- system.time(
    # DSW_DEMEAN_TOL (diagnostic only): tighter demeaning tolerance; default = feols default (1e-6)
    fit <- fwl_fit(fwl_env, refs = fwl_refs, batch = 3L, chunk = 2e6, nthreads = 16L,
                   tol = if (nzchar(Sys.getenv("DSW_DEMEAN_TOL"))) as.numeric(Sys.getenv("DSW_DEMEAN_TOL")) else eval(formals(fixest::feols)$fixef.tol))
  )
  cat(sprintf("FWL elapsed: %.1f s (demean %.1f, X'WX %.1f, vcov %.1f); N = %s; n coef = %d\n", tm_fit[["elapsed"]], fit$demean_s, fit$cross_s, fit$vcov_s,
              format(fit$nobs, big.mark = ","), nrow(fit$coeftable)))
  cat(sprintf("FWL: K = %d (K_raw %d), adj_K = %.10f, adj_G = %.10f, G = %s, df_t = %d, vcov fixed = %s, R2 = %.6f\n",
              fit$K, fit$K_raw, fit$adj_K, fit$adj_G, paste(fit$G, collapse = "/"), fit$df_t, fit$vcov_fixed, fit$r2))
  tm <- c(elapsed = tm_fit[["elapsed"]])
  fit_common <- list(nobs = fit$nobs, K = fit$K, K_raw = fit$K_raw, fe_sizes = fit$fe_sizes, nested = fit$nested,
                     adj_K = fit$adj_K, adj_G = fit$adj_G, G = fit$G, df_t = fit$df_t,
                     seconds = tm_fit[["elapsed"]], demean_s = fit$demean_s, cross_s = fit$cross_s,
                     vcov_s = fit$vcov_s, n_singletons = fit$n_singletons, n_trips_est = fit$n_trips_est)
  by_outcome <- lapply(fit$outcomes, function(o) {
    cts <- o$coeftable; cts$term <- rownames(cts)
    list(coeftable = cts, vcov = o$vcov, fit_info = c(fit_common, list(r2 = o$r2, vcov_fixed = o$vcov_fixed)))
  })
  if (!decomp) names(by_outcome) <- "driver_share"
  fit_info <- by_outcome[[1]]$fit_info
  ct <- by_outcome[[1]]$coeftable
  vcov_mat <- by_outcome[[1]]$vcov
}
if (exists("df")) rm(df); gc()

# ---- outputs ------------------------------------------------------------
dict <- c(pu_precip_bin = "Origin rain, current hour (mm/h)", do_precip_bin = "Dest. rain, current hour (mm/h)",
          pu_rain6h_bin = "Origin rain, prev. 6 h (mm)", do_rain6h_bin = "Dest. rain, prev. 6 h (mm)")
# Post-singleton N (FWL reports the estimation sample; the feols path only knows the cell count).
n_cells_note <- if (engine == "fwl") fit_info$nobs else n_cells
n_trips_note <- if (engine == "fwl") fit_info$n_trips_est else n_trips
notes_txt <- paste0(
  if (decomp) paste0("Dependent variables (trip level, cell means): driver share = driver_pay / base_passenger_fare; log fare = ln(base_passenger_fare); log pay = ln(driver_pay); log share = ln(driver_pay / base_passenger_fare) = log pay - log fare exactly, so the log-share coefficient equals the log-pay coefficient minus the log-fare coefficient. ",
                     "Coefficients on the log outcomes are in log points (x100 is approximately a percent change). ",
                     "Log fare and log pay also absorb changes in trip length and duration (composition), whereas the share is a ratio of the two on the same trips. ")
  else "Dependent variable: driver_share = driver_pay / base_passenger_fare (trip level, cell mean). ",
  "Current-hour rain bins (mm/h, left-closed) at origin (pickup hour) and destination (dropoff hour); reference bin is dry, below 0.1 mm/h. ",
  if (use_r6) "Previous-6-hour rain bins (mm, left-closed): total rain in hours t-6 to t-1 before the pickup (origin) or dropoff (destination) hour, excluding the current hour, requiring at least 5 of the 6 hours observed; reference bin is dry, below 0.1 mm. " else "",
  "No temperature controls. ",
  "Trips ending outside NYC (zone 265) are kept; their destination-rain indicators are absorbed by the destination-zone x hour FE, so they inform only origin-rain coefficients. ",
  "Standard errors two-way clustered by pickup taxi zone and pickup date. ",
  "Observations are OD cells (platform x PU zone x DO zone x pickup hour x dropoff hour) weighted by trips per cell, so estimates equal trip-level OLS. ",
  "Fixed effects: platform, PU zone x pickup hour-of-day, DO zone x dropoff hour-of-day, month, day-of-week. ",
  "No date fixed effect: identification includes variation across days within a month as well as across zones and hours. ",
  "Access-a-Ride trips excluded. Significance: *** p<0.01, ** p<0.05, * p<0.1. ",
  sprintf("N cells = %s%s; N trips = %s; months = %s.", format(n_cells_note, big.mark = ","), if (engine == "fwl") " (after fixed-effect singleton removal)" else "", format(n_trips_note, big.mark = ","), paste(months, collapse = ",")))
tex_path <- sprintf("output/reg/driver_share_weather_bins_%s.tex", tag)
fe_lab <- c("Platform (company)", "PU zone x pickup hour-of-day", "DO zone x dropoff hour-of-day", "Month", "Day-of-week")
cl_lab <- "pickup zone \\& pickup date"
if (!decomp) {
  if (engine == "feols") {
    etable(est, dict = dict, fitstat = ~ n + r2, tex = TRUE, file = tex_path, replace = TRUE,
           signif.code = c("***" = 0.01, "**" = 0.05, "*" = 0.10),
           headers = list("Sample:" = tag), notes = notes_txt)
  } else {
    notes_fwl <- paste0(notes_txt, " Estimated by exact batched FWL; validated against fixest::feols on Aug-Sep 2021 to 1e-6.")
    fwl_etable_tex(fit, dict = dict, tag = tag, notes = notes_fwl, path = tex_path,
                   fe_labels = fe_lab, cluster_label = cl_lab)
  }
  wrap_for_beamer(tex_path)
}

saveRDS(list(coeftable = ct, vcov = vcov_mat, fit_info = fit_info, nobs = fit_info$nobs, n_cells = n_cells, n_trips = n_trips,
             n_cells_na_dropped = n_cells_na, n_trips_na_dropped = n_trips_na, n_outside_trips = n_outside_trips,
             feols_seconds = tm[["elapsed"]], months = months, tag = tag, spec = spec, engine = engine,
             by_outcome = by_outcome),
        sprintf("output/reg/driver_share_weather_bins_%s.rds", tag))

facets <- c(pu_precip_bin = "Origin rain, current hour (mm/h)", do_precip_bin = "Destination rain, current hour (mm/h)",
            pu_rain6h_bin = "Origin rain, previous 6 h (mm)", do_rain6h_bin = "Destination rain, previous 6 h (mm)")
lv <- list(pu_precip_bin = PRECIP_LABELS, do_precip_bin = PRECIP_LABELS, pu_rain6h_bin = R6_LABELS, do_rain6h_bin = R6_LABELS)
facets <- facets[bvars]

if (!decomp) {
  plot_df <- do.call(rbind, lapply(names(facets), function(v) {
    rows <- ct[startsWith(ct$term, paste0(v, "::")), ]
    b <- sub(paste0(v, "::"), "", rows$term, fixed = TRUE)
    d <- data.frame(var = v, bin = c(b, REF), est = c(rows$Estimate, 0), se = c(rows$`Std. Error`, 0))
    d$bin <- factor(d$bin, levels = lv[[v]]); d$facet <- factor(facets[[v]], levels = facets); d
  }))
  plot_df$lo <- plot_df$est - 1.96 * plot_df$se; plot_df$hi <- plot_df$est + 1.96 * plot_df$se
  p <- ggplot(plot_df, aes(bin, est)) +
    geom_hline(yintercept = 0, linewidth = 0.3) + geom_pointrange(aes(ymin = lo, ymax = hi), size = 0.3) +
    facet_wrap(~facet, scales = "free_x", ncol = 2) +
    labs(x = "Bin", y = "Coefficient on driver_share (vs. dry)") +
    theme_classic(base_size = 10) + theme(axis.text.x = element_text(angle = 45, hjust = 1))
  ggsave(sprintf("output/fig/driver_share_weather_bins_%s.png", tag), p, width = 10, height = if (use_r6) 8 else 4.5, dpi = 300)
  if (engine == "feols") print(etable(est, dict = dict, fitstat = ~ n + r2, signif.code = c("***" = 0.01, "**" = 0.05, "*" = 0.10)))
  cat("coefficients (full precision):\n"); print(setNames(ct$Estimate, ct$term), digits = 10)
} else {
  # ---- decomposition outputs: 4-column table, fare-vs-pay figure, rds -------------
  dtag <- sub("_decomp$", "", tag)
  # identity check: beta(log_share) = beta(log_pay) - beta(log_fare)
  e_share <- by_outcome$log_share$coeftable$Estimate
  e_diff <- by_outcome$log_pay$coeftable$Estimate - by_outcome$log_fare$coeftable$Estimate
  id_abs <- max(abs(e_share - e_diff)); id_rel <- max(abs(e_share - e_diff) / pmax(abs(e_share), 1e-12))
  cat(sprintf("IDENTITY log_share = log_pay - log_fare: max abs diff %.3g, max rel diff %.3g (tolerance 1e-10)\n", id_abs, id_rel))
  if (engine == "fwl") {
    fit$outcomes <- fit$outcomes[ynames]
    dec_tex <- sprintf("output/reg/driver_share_decomp_%s.tex", dtag)
    notes_fwl <- paste0(notes_txt, " Estimated by exact batched FWL; validated against fixest::feols on Aug-Sep 2021 to 1e-6.")
    fwl_etable_tex_multi(fit, dict = dict, col_labels = c("driver\\_share", "log fare", "log pay", "log share"),
                         tag = tag, notes = notes_fwl, path = dec_tex, fe_labels = fe_lab, cluster_label = cl_lab)
    wrap_for_beamer(dec_tex)
    # figure: log fare vs log pay, dodged, 95% CI, reference (dry) at 0
    pdf <- do.call(rbind, lapply(c("log_fare", "log_pay"), function(o) {
      cto <- by_outcome[[o]]$coeftable
      do.call(rbind, lapply(names(facets), function(v) {
        rows <- cto[startsWith(cto$term, paste0(v, "::")), ]
        b <- sub(paste0(v, "::"), "", rows$term, fixed = TRUE)
        d <- data.frame(outcome = o, var = v, bin = c(b, REF), est = c(rows$Estimate, 0), se = c(rows$`Std. Error`, 0))
        d$bin <- factor(d$bin, levels = lv[[v]]); d$facet <- factor(facets[[v]], levels = facets); d
      }))
    }))
    pdf$outcome <- factor(pdf$outcome, levels = c("log_fare", "log_pay"), labels = c("Log fare", "Log driver pay"))
    pdf$lo <- pdf$est - 1.96 * pdf$se; pdf$hi <- pdf$est + 1.96 * pdf$se
    pd <- position_dodge(width = 0.6)
    pp <- ggplot(pdf, aes(bin, est, colour = outcome)) +
      geom_hline(yintercept = 0, linewidth = 0.3) +
      geom_pointrange(aes(ymin = lo, ymax = hi), size = 0.25, position = pd) +
      scale_colour_manual(values = c("Log fare" = "#1b6ca8", "Log driver pay" = "#d95f02"), name = NULL) +
      facet_wrap(~facet, scales = "free_x", ncol = 2) +
      labs(x = "Bin", y = "Coefficient (log points, vs. dry bin)") +
      theme_classic(base_size = 10) + theme(axis.text.x = element_text(angle = 45, hjust = 1), legend.position = "bottom")
    ggsave(sprintf("output/fig/driver_share_decomp_%s.png", dtag), pp, width = 10, height = 7, dpi = 300)
    saveRDS(list(by_outcome = by_outcome, nobs = fit_info$nobs, n_trips_est = fit_info$n_trips_est, K = fit_info$K, K_raw = fit_info$K_raw,
                 adj_K = fit_info$adj_K, adj_G = fit_info$adj_G, G = fit_info$G, df_t = fit_info$df_t,
                 timings = c(total = fit_info$seconds, demean = fit_info$demean_s, xwx = fit_info$cross_s, vcov = fit_info$vcov_s),
                 identity = c(max_abs = id_abs, max_rel = id_rel), months = months, tag = tag,
                 n_cells_na_dropped = n_cells_na, n_trips_na_dropped = n_trips_na),
            sprintf("output/reg/driver_share_decomp_%s.rds", dtag))
  }
  for (o in ynames) { cat("==", o, "\n"); print(setNames(by_outcome[[o]]$coeftable$Estimate, by_outcome[[o]]$coeftable$term), digits = 8) }
}
