# ============================================================
# Script: ida_first_pass.r
# Purpose: D4 -- the three-window (pre_matched/during/post_matched) x firm
#          first-pass comparison. This is CLAUDE.md Design 2 (simple
#          before/after in affected zones, generalized to citywide firm
#          totals here): no control for citywide time shocks or seasonality.
#          Report as a DESCRIPTIVE BENCHMARK ONLY -- never as a causal
#          estimate. The causal work (within-city spatial DiD) needs the
#          weather panel and is out of scope for this script.
#          pre_matched/post_matched replace the old full-calendar-day
#          pre/post comparison: same clock-hour window as the storm (9h),
#          replicated across 14 days 2-4 weeks before/after, pooled. This
#          isolates the storm's effect on that time-of-day slice instead of
#          conflating it with ordinary daytime-vs-evening demand patterns.
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
stopifnot(all(c("pre_matched", "during", "post_matched") %in% window_agg$window))

# ------------------------------------------------------------------
# Table: firms in columns, measures in rows, three window blocks
# ------------------------------------------------------------------

platform_order <- c("Uber", "Lyft", "Via", "All")
window_order <- c("pre_matched", "during", "post_matched")
window_labels <- c(
  pre_matched = "Pre-Ida (matched hrs, 2-4 wks before)",
  during = "During Ida (9 hours)",
  post_matched = "Post-Ida (matched hrs, 2-4 wks after)"
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
  list(label = "Platform margin per trip",    col = "platform_margin_per_trip",  fmt = fmt_dollar),
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
n_replicates <- windows_json$matched_window_params$n_replicates
offset_min <- windows_json$matched_window_params$offset_min_days
offset_max <- windows_json$matched_window_params$offset_max_days

# JSON timestamps carry a "-04:00" offset suffix that base R's as.POSIXct()
# silently fails to parse (it falls back to date-only, truncating the time
# of day with no warning -- confirmed by inspection, not just assumption).
# Strip the offset and parse as naive local wall-clock instead, matching
# the convention already used in clean_hvfhv.py's load_windows(): correct
# because the whole span sits inside EDT with no DST transition.
parse_local <- function(iso) {
  as.POSIXct(sub("[+-][0-9]{2}:[0-9]{2}$", "", iso),
             format = "%Y-%m-%dT%H:%M:%S", tz = "America/New_York")
}

pre_matched_earliest <- min(parse_local(windows_json$pre_matched_windows$start))
pre_matched_latest <- max(parse_local(windows_json$pre_matched_windows$end))
post_matched_earliest <- min(parse_local(windows_json$post_matched_windows$start))
post_matched_latest <- max(parse_local(windows_json$post_matched_windows$end))
during_hours <- as.numeric(parse_local(during_end) - parse_local(during_start), units = "hours")

table_notes <- paste0(
  "Descriptive benchmark only (CLAUDE.md Design 2) -- no control for citywide time shocks or ",
  "seasonality; NOT a causal estimate. Windows derived from observed ASOS rainfall (threshold ",
  threshold, " in/hr), never hardcoded: during ", during_start, " to ", during_end,
  " (peak hourly rain at ", peak_hour, "). Pre-Ida and Post-Ida are TIME-OF-DAY-MATCHED windows: ",
  "the same ", during_hours,
  "-hour clock-time span as the During-Ida window, replicated on ", n_replicates,
  " days each side at offsets of ", offset_min, "-", offset_max,
  " days before/after the storm, then pooled -- NOT the full-calendar-day pre/post comparison ",
  "used in earlier drafts of this table. This isolates the storm's effect on that specific ",
  "time-of-day slice instead of conflating it with ordinary daytime-vs-evening demand patterns. ",
  "Pre-Ida matched range: ", format(pre_matched_earliest, "%Y-%m-%d %H:%M"), " to ",
  format(pre_matched_latest, "%Y-%m-%d %H:%M"), ". Post-Ida matched range: ",
  format(post_matched_earliest, "%Y-%m-%d %H:%M"), " to ", format(post_matched_latest, "%Y-%m-%d %H:%M"),
  ". Neither matched range crosses a federal holiday (US Labor Day 2021-09-06 falls between them, ",
  "outside both). Ratio/rate measures are pooled across the ", n_replicates,
  " replicate windows and computed as ratios of sums, not means of ratios, per this project's ",
  "convention. Platform margin = base\\_passenger\\_fare - driver\\_pay: firm gross take per trip, ",
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
  "hours) is far shorter than the pooled 5.25-day matched windows, so raw totals are not ",
  "comparable across windows on their own."
)

kbl_tex <- full_df %>%
  kbl(format = "latex", booktabs = TRUE, escape = FALSE, align = "lrrrr",
      caption = "Firm x window first-pass comparison (descriptive benchmark)",
      label = "firm_window_first_pass") %>%
  kable_styling(latex_options = c("hold_position", "scale_down")) %>%
  pack_rows("Per-day / rate measures -- Pre-Ida (matched hrs)", 1, 14) %>%
  pack_rows("Per-day / rate measures -- During Ida", 15, 28) %>%
  pack_rows("Per-day / rate measures -- Post-Ida (matched hrs)", 29, 42) %>%
  pack_rows("Raw totals -- Pre-Ida (matched hrs) (NOT comparable across windows, see notes)", 43, 45) %>%
  pack_rows("Raw totals -- During Ida (NOT comparable across windows, see notes)", 46, 48) %>%
  pack_rows("Raw totals -- Post-Ida (matched hrs) (NOT comparable across windows, see notes)", 49, 51) %>%
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

during_start_dt <- parse_local(during_start)
during_end_dt <- parse_local(during_end)

day_agg <- day_agg %>% filter(platform != "All")
day_agg$date <- as.Date(day_agg$date)

measure_specs <- list(
  list(col = "n_trips", label = "Trips per 9-hour period"),
  list(col = "revenue_passenger", label = "Revenue per 9-hour period ($)"),
  list(col = "fare_per_mile", label = "Fare per mile ($)"),
  list(col = "mean_trip_miles", label = "Mean trip distance (mi)"),
  list(col = "driver_share", label = "Driver share (ex-tips)"),
  list(col = "platform_margin_per_trip", label = "Platform margin per trip ($)")
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

# Each point in day_agg is now a day-ANCHORED 9-hour window (17:00-02:00
# local, the same clock-hour span as During-Ida), not a full calendar day --
# see build_firm_window_aggregates.py. During-Ida's own window IS that
# anchor formula applied to 2021-09-01 (During-Ida = [09-01 17:00, 09-02
# 02:00)), so it shows up as a single point at that date rather than
# spanning two dates; shade just that one date's column accordingly.
during_anchor_date <- as.Date(during_start_dt)

# Second comparison band: Tropical Storm Henri. Verified against the same
# ASOS station data used to derive Ida's window (raw_data/weather/asos/
# asos_nyc_2021.csv, max p01i across KNYC/KLGA/KJFK/KEWR, local time) -- NOT
# hardcoded from memory. Peak hourly rain in the Aug 19-23 span: 1.94 in at
# 2021-08-21 23:00 local, which falls inside the [17:00, next-day 02:00)
# anchor window for 2021-08-21 -- the same clock-hour span as During-Ida, so
# it plots as a single date exactly like the Ida band. A second, more
# sustained but lower-intensity round of rain fell 2021-08-22 07:00-16:00
# (daytime); it does not appear as its own shaded date because it falls
# entirely outside every 9-hour evening/overnight window plotted here.
henri_anchor_date <- as.Date("2021-08-21")

storm_events <- data.frame(
  event = factor(c("Tropical Storm Henri", "Hurricane Ida"),
                  levels = c("Tropical Storm Henri", "Hurricane Ida")),
  xmin = c(henri_anchor_date, during_anchor_date) - 0.5,
  xmax = c(henri_anchor_date, during_anchor_date) + 0.5
)

fig_caption_raw <- paste0(
  "Each point is a 9-hour evening/overnight window (17:00-02:00 local, the same ",
  "clock-hours as During-Ida), anchored to that calendar date -- not a full ",
  "calendar day -- so every panel compares like time-of-day slices throughout. ",
  "Shaded columns: Hurricane Ida (2021-09-01 17:00 to 2021-09-02 02:00 local) and ",
  "Tropical Storm Henri (2021-08-21 17:00 to 2021-08-22 02:00 local, peak hourly rain ",
  "1.94in at 23:00 -- Henri's rain continued into daytime 2021-08-22, outside the ",
  "9-hour windows shown here). Platform margin = base_passenger_fare - driver_pay ",
  "(firm gross take per trip, not accounting profit). Descriptive benchmark, not a ",
  "causal estimate."
)
# ggplot only breaks plot.caption on literal "\n" -- it does not auto-wrap
# long strings to the plot width, so a caption this long must be pre-wrapped
# or it silently overflows past the bottom of the saved image.
fig_caption <- paste(strwrap(fig_caption_raw, width = 130), collapse = "\n")

p <- ggplot(long_df, aes(x = date, y = value, color = platform)) +
  geom_rect(data = storm_events, inherit.aes = FALSE,
            aes(xmin = xmin, xmax = xmax, fill = event),
            ymin = -Inf, ymax = Inf, alpha = 0.15) +
  scale_fill_manual(values = c("Tropical Storm Henri" = "blue", "Hurricane Ida" = "red"),
                     name = "Storm event") +
  geom_line() +
  geom_point(size = 0.8) +
  facet_wrap(~measure, scales = "free_y", ncol = 2) +
  labs(x = NULL, y = NULL, color = "Platform", caption = fig_caption) +
  theme_bw() +
  theme(legend.position = "top", axis.text.x = element_text(angle = 45, hjust = 1),
        plot.caption = element_text(size = 7, hjust = 0, lineheight = 1.2),
        plot.margin = margin(t = 5.5, r = 5.5, b = 11, l = 5.5))

ggsave(FIG_OUT, plot = p, width = 9, height = 9, dpi = 300)
cat(sprintf("Wrote %s\n", FIG_OUT))

# ------------------------------------------------------------------
# Econometric sanity checks (verification-protocol.md)
# ------------------------------------------------------------------

cat("\n--- Sanity checks ---\n")
pre_all <- window_agg %>% filter(window == "pre_matched", platform == "All")
during_all <- window_agg %>% filter(window == "during", platform == "All")
post_all <- window_agg %>% filter(window == "post_matched", platform == "All")

cat(sprintf("Pre-matched-window platform_margin_per_trip: $%.2f (old full-day pre was ~$5.24 -- this is an evening/overnight-only population, may genuinely differ)\n", pre_all$platform_margin_per_trip))
cat(sprintf("Pre-matched-window driver_share: %.3f (old full-day pre was ~0.79)\n", pre_all$driver_share))
cat(sprintf("Pre-matched-window share_margin_negative: %.2f%% (old full-day pre was ~18%%)\n", 100 * pre_all$share_margin_negative))
cat(sprintf("Citywide trips_per_day, pre_matched/during/post_matched: %.0f / %.0f / %.0f (expect hundreds of thousands)\n",
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
