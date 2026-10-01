# ============================================================
# Script: fwl_compare.r
# Purpose: Compare an FWL fit with a fixest::feols fit of the same spec/sample, per outcome:
#          coefficients, SEs, p-values, stars, N, coefficient set, K / adjustments.
# Usage:   Rscript --vanilla code/analysis/fwl_compare.r <feols_tag> <fwl_tag> <out_tag>
# Inputs:  output/reg/driver_share_weather_bins_{tag}.rds (written by driver_share_weather_bins.r;
#          multi-outcome runs carry $by_outcome, single-outcome runs are treated as driver_share)
# Outputs: output/sum/fwl_vs_feols_{out_tag}.csv (one row per outcome x coefficient)
# Pass rule (user criterion): relative diff < 1e-6 on every coefficient and SE; absolute
#          diff < 1e-6 on every p-value; identical stars (*** 0.01, ** 0.05, * 0.10);
#          identical N; identical coefficient set. Every outcome must pass.
# Author: EK  Date: 2026-10-01
# ============================================================
args <- commandArgs(trailingOnly = TRUE)
a <- readRDS(sprintf("output/reg/driver_share_weather_bins_%s.rds", args[1]))
b <- readRDS(sprintf("output/reg/driver_share_weather_bins_%s.rds", args[2]))
stars <- function(p) ifelse(p < 0.01, "***", ifelse(p < 0.05, "**", ifelse(p < 0.10, "*", "")))
rel <- function(x, y) abs(x - y) / pmax(abs(x), .Machine$double.eps)
get_out <- function(r) if (!is.null(r$by_outcome)) r$by_outcome else
  list(driver_share = list(coeftable = r$coeftable, vcov = r$vcov, fit_info = r$fit_info))
oa <- get_out(a); ob <- get_out(b)
stopifnot(setequal(names(oa), names(ob)))
all_pass <- TRUE; rows <- list()
for (o in names(oa)) {
  ca <- oa[[o]]$coeftable; cb <- ob[[o]]$coeftable
  fa <- oa[[o]]$fit_info; fb <- ob[[o]]$fit_info
  same_set <- setequal(rownames(ca), rownames(cb)) && nrow(ca) == nrow(cb)
  common <- intersect(rownames(ca), rownames(cb))
  out <- data.frame(outcome = o, term = common,
                    feols_est = ca[common, "Estimate"], fwl_est = cb[common, "Estimate"],
                    rel_diff_est = rel(ca[common, "Estimate"], cb[common, "Estimate"]),
                    feols_se = ca[common, "Std. Error"], fwl_se = cb[common, "Std. Error"],
                    rel_diff_se = rel(ca[common, "Std. Error"], cb[common, "Std. Error"]),
                    feols_p = ca[common, "Pr(>|t|)"], fwl_p = cb[common, "Pr(>|t|)"], stringsAsFactors = FALSE)
  out$abs_diff_p <- abs(out$feols_p - out$fwl_p)
  out$stars_feols <- stars(out$feols_p); out$stars_fwl <- stars(out$fwl_p)
  rows[[o]] <- out
  res <- c(coef_set = same_set, est = max(out$rel_diff_est) < 1e-6, se = max(out$rel_diff_se) < 1e-6,
           p = max(out$abs_diff_p) < 1e-6, stars = all(out$stars_feols == out$stars_fwl),
           N = identical(as.numeric(fa$nobs), as.numeric(fb$nobs)))
  cat(sprintf("[%s] coef set identical %s (%d vs %d) | max rel diff coef %.3g, SE %.3g | max abs diff p %.3g | stars identical %s | N feols %s FWL %s\n",
              o, same_set, nrow(ca), nrow(cb), max(out$rel_diff_est), max(out$rel_diff_se), max(out$abs_diff_p), res[["stars"]],
              format(fa$nobs, big.mark = ","), format(fb$nobs, big.mark = ",")))
  cat(sprintf("[%s] K: feols %s (nparams %s) | FWL %s (K_raw %s); adj_K FWL %.10f vs feols-implied %.10f; df.t feols %s FWL %s; R2 %.8f vs %.8f\n",
              o, fa$K, fa$nparams, fb$K, fb$K_raw, fb$adj_K, (fa$nobs - 1) / (fa$nobs - fa$K), fa$df_t, fb$df_t, fa$r2, fb$r2))
  va <- oa[[o]]$vcov; vb <- ob[[o]]$vcov
  if (!is.null(va) && !is.null(vb) && identical(rownames(va), rownames(vb)))
    cat(sprintf("[%s] max rel diff in full vcov (scaled by sqrt(diag)): %.3g\n", o, max(abs(va - vb) / sqrt(outer(diag(va), diag(va))))))
  cat(sprintf("[%s] %s\n", o, if (all(res)) "PASS" else paste("FAIL on", paste(names(res)[!res], collapse = ","))))
  all_pass <- all_pass && all(res)
}
write.csv(do.call(rbind, rows), sprintf("output/sum/fwl_vs_feols_%s.csv", args[3]), row.names = FALSE)
cat(sprintf("TOTAL: %s\n", if (all_pass) "PASS" else "FAIL"))
