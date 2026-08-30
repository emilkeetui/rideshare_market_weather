# ============================================================
# Script: ida_first_pass.r
# Purpose: D4 -- the three-window (pre/during/post) x firm first-pass
#          comparison. This is CLAUDE.md Design 2 (simple before/after in
#          affected zones, generalized to citywide firm totals here): no
#          control for citywide time shocks, seasonality, or the Labor Day
#          holiday. Report as a DESCRIPTIVE BENCHMARK ONLY -- never as a
#          causal estimate. The causal work (within-city spatial DiD) needs
#          the weather panel and is out of scope for this script.
# Inputs: clean_data/firm_window_aggregates.parquet
#         clean_data/firm_day_aggregates.parquet
#         clean_data/ida_event_windows.json
# Outputs: output/reg/firm_window_first_pass.tex
#          output/fig/firm_window_first_pass.png
# Author: EK  Date: 2026-08-29
# ============================================================

library(arrow)
library(dplyr)
library(ggplot2)
library(kableExtra)
library(jsonlite)

# Run from the project root, per this project's convention (see
# .claude/rules/verification-protocol.md): Rscript.exe --vanilla
# code/analysis/ida_first_pass.r
PROJECT_ROOT <- normalizePath(getwd())
source(file.path(PROJECT_ROOT, "code", "analysis", "fhv_reg.r"))

WINDOW_PATH <- file.path(PROJECT_ROOT, "clean_data", "firm_window_aggregates.parquet")
DAY_PATH <- file.path(PROJECT_ROOT, "clean_data", "firm_day_aggregates.parquet")
WINDOWS_JSON_PATH <- file.path(PROJECT_ROOT, "clean_data", "ida_event_windows.json")
TABLE_OUT <- file.path(PROJECT_ROOT, "output", "reg", "firm_window_first_pass.tex")
FIG_OUT <- file.path(PROJECT_ROOT, "output", "fig", "firm_window_first_pass.png")

# --- load and check schema (cross-language check: written by pandas) ---
window_agg <- read_parquet(WINDOW_PATH)
day_agg <- read_parquet(DAY_PATH)
windows_json <- fromJSON(WINDOWS_JSON_PATH)

cat("str(window_agg):\n")
str(window_agg)
cat("\nstr(day_agg$date):\n")
str(day_agg$date)

stopifnot(is.numeric(window_agg$n_trips))
stopifnot(all(c("pre", "during", "post") %in% window_agg$window))

# ------------------------------------------------------------------
# Table: firms in columns, measures in rows, three window blocks
# ------------------------------------------------------------------

platform_order <- c("Uber", "Lyft", "Via", "All")
window_order <- c("pre", "during", "post")
window_labels <- c(
  pre = "Pre-Ida (14 days)",
  during = "During Ida (9 hours)",
  post = "Post-Ida (14 days)"
)

fmt_dollar <- function(x) sprintf("$%.2f", x)
fmt_dollar0 <- function(x) sprintf("$%s", formatC(round(x), format = "d", big.mark = ","))
fmt_pct <- function(x) sprintf("%.1f%%", 100 * x)
fmt_num <- function(x, digits = 1) sprintf(paste0("%.", digits, "f"), x)
fmt_int <- function(x) formatC(round(x), format = "d", big.mark = ",")

# Per-day / rate measures -- the headline block. Every level comparison
# here is per-day (or a ratio), never a raw total (plan Step 7: the
# `during` window is 0.375 days, so a raw total would just encode window
# length as a "storm effect").
rate_rows <- list(
  list(label = "Trips per day",              col = "trips_per_day",             fmt = fmt_int),
  list(label = "Revenue per day",             col = "revenue_passenger_per_day", fmt = fmt_dollar0),
  list(label = "Platform margin per day",     col = "platform_margin_per_day",   fmt = fmt_dollar0),
  list(label = "Fare per trip",               col = "fare_per_trip",             fmt = fmt_dollar),
  list(label = "Fare per mile",               col = "fare_per_mile",             fmt = fmt_dollar),
  list(label = "Fare per minute",             col = "fare_per_minute",           fmt = fmt_dollar),
  list(label = "Profit (margin) per trip",    col = "profit_per_trip",           fmt = fmt_dollar),
  list(label = "Driver share (ex-tips)",      col = "driver_share",              fmt = fmt_pct),
  list(label = "Driver share (incl. tips)",   col = "driver_share_incl_tips",    fmt = fmt_pct),
  list(label = "Mean trip distance (mi)",     col = "mean_trip_miles",           fmt = function(x) fmt_num(x, 2)),
  list(label = "Mean speed (mph)",            col = "mean_speed_mph",            fmt = function(x) fmt_num(x, 1)),
  list(label = "Mean wait time (s)",          col = "mean_wait_time",            fmt = function(x) fmt_num(x, 0)),
  list(label = "Share margin negative",       col = "share_margin_negative",     fmt = fmt_pct),
  list(label = "Share shared match",          col = "share_shared_match",        fmt = fmt_pct)
)

# Raw-total block -- clearly labelled separate section per plan, so a
# reader cannot mistake a smaller `during` total for a storm effect when it
# is mechanically just a shorter window.
total_rows <- list(
  list(label = "N trips (raw total)",         col = "n_trips",             fmt = fmt_int),
  list(label = "Revenue, \\$ (raw total)",    col = "revenue_passenger",   fmt = fmt_dollar0),
  list(label = "Platform margin, \\$ (raw total)", col = "platform_margin", fmt = fmt_dollar0)
)

build_block <- function(agg, rows_spec, window_name) {
  sub <- agg %>% filter(window == window_name)
  out <- sapply(rows_spec, function(r) {
    vals <- sapply(platform_order, function(p) {
      v <- sub[[r$col]][sub$platform == p]
      if (length(v) == 0 || is.na(v)) return("--")
      r$fmt(v)
    })
    vals
  })
  out <- t(out)
  rownames(out) <- sapply(rows_spec, function(r) r$label)
  colnames(out) <- platform_order
  out
}

rate_blocks <- lapply(window_order, function(w) build_block(window_agg, rate_rows, w))
total_blocks <- lapply(window_order, function(w) build_block(window_agg, total_rows, w))

full_table <- rbind(rate_blocks[[1]], rate_blocks[[2]], rate_blocks[[3]],
                    total_blocks[[1]], total_blocks[[2]], total_blocks[[3]])
# rbind()/as.data.frame() would silently mangle the row labels: duplicate
# rownames across the pre/during/post blocks get ".1"/".2" appended and
# spaces get replaced with dots via make.names(). Build the Measure column
# explicitly from the original label strings instead of trusting rownames().
measure_labels <- c(rep(sapply(rate_rows, function(r) r$label), 3),
                    rep(sapply(total_rows, function(r) r$label), 3))
full_df <- as.data.frame(full_table, stringsAsFactors = FALSE)
rownames(full_df) <- NULL
full_df <- cbind(Measure = measure_labels, full_df)

n_rate <- length(rate_rows)
n_tot <- length(total_rows)

peak_hour <- windows_json$peak_hour_local
threshold <- windows_json$storm_threshold_in
during_start <- windows_json$windows$during$start
during_end <- windows_json$windows$during$end
pre_start <- windows_json$windows$pre$start
pre_end <- windows_json$windows$pre$end
post_start <- windows_json$windows$post$start
post_end <- windows_json$windows$post$end

table_notes <- paste0(
  "Descriptive benchmark only (CLAUDE.md Design 2) -- no control for citywide time shocks, ",
  "seasonality, or the Labor Day holiday; NOT a causal estimate. Windows derived from ",
  "observed ASOS rainfall (threshold ", threshold, " in/hr), never hardcoded: pre ", pre_start,
  " to ", pre_end, "; during ", during_start, " to ", during_end,
  " (peak hourly rain at ", peak_hour, "); post ", post_start, " to ", post_end,
  ". US Labor Day (2021-09-06) falls inside the post window. ",
  "Platform margin = base\\_passenger\\_fare - driver\\_pay: firm gross take per trip, ",
  "NOT accounting profit -- no insurance, incentives, marketing, or overhead costs are ",
  "netted out. Surcharges the firm collects and remits (tolls, Black Car Fund, sales tax, ",
  "congestion surcharge, airport fee) sit on top of the fare and are never deducted from ",
  "margin. Driver share (ex-tips) = driver\\_pay / fare; driver share (incl. tips) = ",
  "(driver\\_pay + tips) / fare -- driver pay includes tips while firm revenue does not, so ",
  "the incl.-tips version can exceed the fare-based margin identity. N\\_trips counts trips, ",
  "not customers -- no rider ID exists in this data. Juno (HV0002) has zero trips in 2021 ",
  "and is omitted; Via is a small share of trips (see docs/data\\_introduction.md) and its ",
  "per-firm statistics are noisy. All comparisons above the raw-total block are per-day ",
  "(or per-trip); the raw-total block is shown separately because the during window (9 ",
  "hours) is far shorter than the 14-day pre/post windows, so raw totals are not comparable ",
  "across windows on their own."
)

kbl_tex <- full_df %>%
  kbl(format = "latex", booktabs = TRUE, escape = FALSE, align = "lrrrr",
      caption = "Firm x window first-pass comparison (descriptive benchmark)",
      label = "firm_window_first_pass") %>%
  kable_styling(latex_options = c("hold_position", "scale_down")) %>%
  pack_rows("Per-day / rate measures -- Pre-Ida", 1, 14) %>%
  pack_rows("Per-day / rate measures -- During Ida", 15, 28) %>%
  pack_rows("Per-day / rate measures -- Post-Ida", 29, 42) %>%
  pack_rows("Raw totals -- Pre-Ida (NOT comparable across windows, see notes)", 43, 45) %>%
  pack_rows("Raw totals -- During Ida (NOT comparable across windows, see notes)", 46, 48) %>%
  pack_rows("Raw totals -- Post-Ida (NOT comparable across windows, see notes)", 49, 51) %>%
  footnote(general = table_notes, threeparttable = TRUE, escape = FALSE)

dir.create(dirname(TABLE_OUT), showWarnings = FALSE, recursive = TRUE)
writeLines(as.character(kbl_tex), TABLE_OUT)
cat(sprintf("Wrote %s\n", TABLE_OUT))

# This is a hand-assembled table (kableExtra, with \begin{table} and a
# caption/label already emitted by kbl()), NOT bare-tabular etable()
# output -- per CLAUDE.md, wrap_for_beamer() must NOT be called on it.

# ------------------------------------------------------------------
# Figure: small multiples, daily series by platform, storm window shaded
# ------------------------------------------------------------------

during_start_dt <- as.POSIXct(during_start, tz = "America/New_York")
during_end_dt <- as.POSIXct(during_end, tz = "America/New_York")

day_agg <- day_agg %>% filter(platform != "All")
day_agg$date <- as.Date(day_agg$date)

measure_specs <- list(
  list(col = "n_trips", label = "Trips per day"),
  list(col = "revenue_passenger", label = "Revenue per day ($)"),
  list(col = "fare_per_mile", label = "Fare per mile ($)"),
  list(col = "mean_trip_miles", label = "Mean trip distance (mi)"),
  list(col = "platform_margin", label = "Platform margin per day ($)"),
  list(col = "driver_share", label = "Driver share (ex-tips)")
)

long_list <- lapply(measure_specs, function(m) {
  data.frame(
    date = day_agg$date,
    platform = day_agg$platform,
    measure = m$label,
    value = day_agg[[m$col]]
  )
})
long_df <- do.call(rbind, long_list)
long_df$measure <- factor(long_df$measure, levels = sapply(measure_specs, function(m) m$label))

p <- ggplot(long_df, aes(x = date, y = value, color = platform)) +
  annotate("rect", xmin = as.Date(during_start_dt), xmax = as.Date(during_end_dt) + 1,
           ymin = -Inf, ymax = Inf, fill = "red", alpha = 0.12) +
  geom_line() +
  geom_point(size = 0.8) +
  facet_wrap(~measure, scales = "free_y", ncol = 2) +
  labs(x = NULL, y = NULL, color = "Platform",
       caption = "Shaded band: during-Ida window (9 hours, spans parts of 2021-09-01/09-02). Descriptive benchmark, not a causal estimate.") +
  theme_bw() +
  theme(legend.position = "top", axis.text.x = element_text(angle = 45, hjust = 1))

ggsave(FIG_OUT, plot = p, width = 9, height = 8, dpi = 300)
cat(sprintf("Wrote %s\n", FIG_OUT))

# ------------------------------------------------------------------
# Econometric sanity checks (verification-protocol.md)
# ------------------------------------------------------------------

cat("\n--- Sanity checks ---\n")
pre_all <- window_agg %>% filter(window == "pre", platform == "All")
during_all <- window_agg %>% filter(window == "during", platform == "All")
post_all <- window_agg %>% filter(window == "post", platform == "All")

cat(sprintf("Pre-window profit_per_trip: $%.2f (expect ~$5.24)\n", pre_all$profit_per_trip))
cat(sprintf("Pre-window driver_share: %.3f (expect ~0.79)\n", pre_all$driver_share))
cat(sprintf("Pre-window share_margin_negative: %.2f%% (expect ~18%%)\n", 100 * pre_all$share_margin_negative))
cat(sprintf("Citywide trips_per_day, pre/during/post: %.0f / %.0f / %.0f (expect hundreds of thousands)\n",
            pre_all$trips_per_day, during_all$trips_per_day, post_all$trips_per_day))

# Per NOTE: do not flag any change for its sign -- both revenue directions
# are live hypotheses. Only flag implausible MAGNITUDES.
pct_change <- function(a, b) 100 * (b - a) / a
cat(sprintf("\nPre -> during %% change (magnitude check only, sign not evaluated):\n"))
cat(sprintf("  trips_per_day: %+.1f%%\n", pct_change(pre_all$trips_per_day, during_all$trips_per_day)))
cat(sprintf("  fare_per_mile: %+.1f%%\n", pct_change(pre_all$fare_per_mile, during_all$fare_per_mile)))
cat(sprintf("  revenue_passenger_per_day: %+.1f%%\n",
            pct_change(pre_all$revenue_passenger_per_day, during_all$revenue_passenger_per_day)))

if (abs(pct_change(pre_all$fare_per_mile, during_all$fare_per_mile)) > 500) {
  warning("fare_per_mile change exceeds 500% -- implausible magnitude, investigate before reporting.")
}

cat("\nDone.\n")
