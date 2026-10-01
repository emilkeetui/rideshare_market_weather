# ============================================================
# Script: fwl_batched.r
# Purpose: Exact batched Frisch-Waugh-Lovell (FWL) estimator that reproduces
#          fixest::feols(y ~ i(bin1, ref=..) + ... | FE1 + FE2 + ..., weights = w,
#          cluster = ~cl1 + cl2) (default ssc, fixef.rm = "perfect_fit") without
#          materialising the full raw design matrix or feols' working copies.
#          Dummy columns are built a few at a time, demeaned with fixest::demean
#          (same weights / FEs / tol / iter as the feols defaults) and stored as
#          one preallocated matrix; X'WX, X'Wy and the clustered meat are then
#          accumulated in row chunks.
# Inputs: none (function definitions only; sourced by driver_share_weather_bins.r)
# Outputs: none
# Replicates from the fixest 0.14.2 source (read, not guessed):
#   * singleton removal: observations in a FE group of size 1 are removed
#     iteratively until none remain (fixef.rm = "perfect_fit" default),
#   * residuals e = y_demeaned - X_demeaned %*% beta; scores = (w * e) * X_demeaned,
#   * bread = (X'WX)^-1; V = sum over cluster combinations (-1)^(i+1) * meat
#     (pu, date, pu x date); G.df = "min": V * G_min/(G_min - 1);
#     K.adj: V * (n - 1)/(n - K); K from ssc_compute_K with K.fixef = "nonnested"
#     (FEs nested in a cluster variable are discounted), K.exact = FALSE,
#   * non-PD fix: eigen-decomposition, eigenvalues floored at 1e-16 (mat_posdef_fix),
#   * t.df = "min": p-values from t with df = G_min - 1.
# Author: EK  Date: 2026-10-01
# ============================================================

# densify(x): map integer codes to 1..m (order preserving), via a presence table.
fwl_densify <- function(x) {
  x <- as.integer(x)
  r <- x - min(x) + 1L
  present <- tabulate(r) > 0L
  map <- cumsum(present)
  map[r]
}

# Is FE (dense codes f) nested in cluster variable (dense codes g)?
# Nested <=> every FE level occurs with exactly one cluster level.
fwl_is_nested <- function(f, g) {
  pair <- (f - 1L) + max(f) * (g - 1L) + 1  # double: avoids int overflow
  sum(tabulate(pair) > 0L) == max(f)
}

# Cholesky-based collinearity screen on X'WX (columns processed in order): column j is
# excluded when its remaining pivot / original diagonal < tol.
fwl_collin_keep <- function(A, tol) {
  K <- ncol(A); keep <- rep(TRUE, K); R <- matrix(0, K, K)
  for (j in seq_len(K)) {
    kk <- which(keep[seq_len(j - 1L)])
    piv <- A[j, j] - sum(R[kk, j]^2)
    if (!(piv / A[j, j] > tol)) { keep[j] <- FALSE; next }
    R[j, j] <- sqrt(piv)
    if (j < K) for (l in (j + 1L):K) R[j, l] <- (A[j, l] - sum(R[kk, j] * R[kk, l])) / R[j, j]
  }
  keep
}


# fwl_fit(): data_env holds y, w, bins, fe, cl. y is either one numeric vector or a NAMED LIST of
# outcome vectors (multi-outcome, like a feols multi-LHS call): X is demeaned once, all outcomes in
# one demean call, and each outcome gets its own beta, residuals and two-way clustered vcov.
# The sample (singleton removal, columns kept) is common to all outcomes. data_env is CONSUMED.
fwl_fit <- function(data_env, refs, batch = 3L, chunk = 5e6, nthreads = 16L,
                    tol = eval(formals(fixest::feols)$fixef.tol),
                    iter = eval(formals(fixest::feols)$fixef.iter),
                    collin_tol = eval(formals(fixest::feols)$collin.tol),
                    verbose = TRUE) {
  msg <- function(...) if (verbose) cat(format(Sys.time(), "%H:%M:%S"), sprintf(...), "\n")
  t_all <- proc.time()[["elapsed"]]
  ylist <- if (is.list(data_env$y)) data_env$y else list(y = data_env$y)
  onames <- names(ylist); Ky <- length(ylist)
  w <- as.numeric(data_env$w); bins <- data_env$bins
  fe_code <- lapply(data_env$fe, fwl_densify)                # dense FE ids
  cl_code <- lapply(data_env$cl, fwl_densify)                # dense cluster ids
  rm(list = ls(data_env), envir = data_env); gc()
  N0 <- length(ylist[[1]])
  stopifnot(all(lengths(ylist) == N0), all(lengths(fe_code) == N0), all(lengths(cl_code) == N0),
            all(lengths(bins) == N0), length(w) == N0)
  lvls <- lapply(bins, levels)
  codes <- lapply(bins, as.integer)
  rm(bins); gc()

  # ---- 1. singleton removal (iterative, all FE dimensions; common to all outcomes) ----
  keep <- rep(TRUE, N0)
  first_pass <- integer(length(fe_code)); names(first_pass) <- names(fe_code)
  pass <- 0L
  repeat {
    pass <- pass + 1L
    removed <- 0L
    for (nm in names(fe_code)) {
      code <- fe_code[[nm]]
      cnt <- tabulate(code[keep], nbins = max(code))
      drop <- keep & (cnt[code] == 1L)
      nd <- sum(drop)
      if (pass == 1L) first_pass[[nm]] <- nd
      if (nd > 0L) { keep[drop] <- FALSE; removed <- removed + nd }
      rm(drop)
    }
    if (removed == 0L) break
  }
  n_single <- N0 - sum(keep)
  msg("FWL singleton removal: %s observations (first-pass by FE: %s); passes = %d",
      format(n_single, big.mark = ","), paste(first_pass, collapse = "/"), pass)
  if (n_single > 0L) {
    ylist <- lapply(ylist, function(v) v[keep]); w <- w[keep]
    fe_code <- lapply(fe_code, function(v) fwl_densify(v[keep]))   # re-densify on the estimation sample
    cl_code <- lapply(cl_code, function(v) fwl_densify(v[keep]))
    codes <- lapply(codes, function(v) v[keep])
  }
  rm(keep); gc()
  N <- length(ylist[[1]])
  fe_sizes <- vapply(fe_code, max, 1L)
  G <- vapply(cl_code, max, 1L)
  # intersection cluster (dense ids)
  int_raw <- (cl_code[[1]] - 1L) + as.double(G[[1]]) * (cl_code[[2]] - 1L) + 1
  present <- tabulate(int_raw) > 0L
  int_code <- as.integer(cumsum(present)[int_raw]); G_int <- max(int_code)
  rm(int_raw, present)

  # ---- 2. design columns (names as in fixest::i()) -------------------------
  spec <- do.call(rbind, lapply(names(lvls), function(b) {
    lv <- lvls[[b]]; lv <- lv[!lv %in% refs[[b]]]
    data.frame(var = b, level = lv, stringsAsFactors = FALSE)
  }))
  spec$name <- paste0(spec$var, "::", spec$level)
  spec$idx <- mapply(function(v, l) match(l, lvls[[v]]), spec$var, spec$level)
  spec$count <- mapply(function(v, i) sum(codes[[v]] == i), spec$var, spec$idx)
  empty <- spec$count == 0L
  if (any(empty)) msg("FWL: dropping empty columns (as feols does): %s", paste(spec$name[empty], collapse = ", "))
  spec <- spec[!empty, ]; rownames(spec) <- NULL
  K_coef <- nrow(spec)
  gc()

  # weighted total SS of each y (before demeaning) for the overall R2
  wsum <- sum(w)
  sst <- vapply(ylist, function(y) sum(w * (y - sum(w * y) / wsum)^2), 1)

  # ---- 3. demean all y's in one call, then dummy columns in batches ---------
  t_dm <- proc.time()[["elapsed"]]
  fe_list <- unname(fe_code)
  dm1 <- function(X) fixest::demean(X, f = fe_list, weights = w, iter = iter, tol = tol,
                                    nthreads = nthreads, notes = FALSE, as.matrix = TRUE)
  Ymat <- matrix(0, nrow = N, ncol = Ky)
  for (o in seq_len(Ky)) { Ymat[, o] <- ylist[[1]]; ylist[[1]] <- NULL }
  rm(ylist); gc()
  Yt <- dm1(Ymat); rm(Ymat); gc()
  Yt <- matrix(Yt, nrow = N, ncol = Ky)
  msg("  demeaned %d outcome(s) (%.0f s elapsed)", Ky, proc.time()[["elapsed"]] - t_dm)
  Xt <- matrix(0, nrow = N, ncol = K_coef)
  starts <- seq(1L, K_coef, by = batch)
  for (s in starts) {
    j <- s:min(s + batch - 1L, K_coef)
    Xb <- matrix(0, nrow = N, ncol = length(j))
    for (k in seq_along(j)) Xb[, k] <- as.numeric(codes[[spec$var[j[k]]]] == spec$idx[j[k]])
    Xt[, j] <- dm1(Xb)
    rm(Xb); gc(verbose = FALSE)
    msg("  demeaned columns %d-%d of %d (%.0f s elapsed)", min(j), max(j), K_coef, proc.time()[["elapsed"]] - t_dm)
  }
  rm(codes, fe_list); gc()
  demean_s <- proc.time()[["elapsed"]] - t_dm

  chunk_starts <- seq(1, N, by = chunk)
  rng <- function(s) s:min(s + chunk - 1, N)

  # ---- 4. beta (one column per outcome) from X'WX and X'Wy ------------------
  t_x <- proc.time()[["elapsed"]]
  xwx <- matrix(0, K_coef, K_coef); xwy <- matrix(0, K_coef, Ky)
  for (s in chunk_starts) {
    i <- rng(s)
    sw <- sqrt(w[i])
    Xc <- Xt[i, , drop = FALSE] * sw
    xwx <- xwx + crossprod(Xc)
    xwy <- xwy + crossprod(Xc, Yt[i, , drop = FALSE] * sw)
  }
  # Collinearity: feols runs a Cholesky of X'WX that excludes a column when its remaining
  # pivot, relative to its diagonal, falls below collin.tol (default 1e-9); the excluded
  # columns are dropped from the model (and from nparams). Replicated here.
  keep_col <- fwl_collin_keep(xwx, tol = collin_tol)
  if (any(!keep_col)) {
    msg("FWL: dropping %d collinear column(s) (feols collin.tol = %g): %s", sum(!keep_col), collin_tol,
        paste(spec$name[!keep_col], collapse = ", "))
    xwx <- xwx[keep_col, keep_col, drop = FALSE]; xwy <- xwy[keep_col, , drop = FALSE]
    spec <- spec[keep_col, ]; rownames(spec) <- NULL
    colsel <- which(keep_col); K_coef <- nrow(spec)
  } else colsel <- seq_len(K_coef)
  ch <- tryCatch(chol(xwx), error = function(e) NULL)
  if (is.null(ch)) stop("X'WX is not positive definite after collinearity screening")
  bread <- chol2inv(ch)
  B <- bread %*% xwy                                          # K x Ky
  dimnames(bread) <- list(spec$name, spec$name)
  cross_s <- proc.time()[["elapsed"]] - t_x

  # ---- 5. residuals, cluster score sums (per outcome) -----------------------
  t_v <- proc.time()[["elapsed"]]
  zero3 <- function() list(matrix(0, G[[1]], K_coef), matrix(0, G[[2]], K_coef), matrix(0, G_int, K_coef))
  S <- lapply(seq_len(Ky), function(o) zero3())
  ssr <- numeric(Ky)
  acc <- function(M, r) { ix <- as.integer(rownames(r)); M[ix, ] <- M[ix, , drop = FALSE] + r; M }
  for (s in chunk_starts) {
    i <- rng(s)
    Xc <- Xt[i, colsel, drop = FALSE]
    E <- Yt[i, , drop = FALSE] - Xc %*% B
    ssr <- ssr + colSums(w[i] * E^2)
    for (o in seq_len(Ky)) {
      sc <- Xc * (E[, o] * w[i])                              # scores (w e) x_tilde
      S[[o]][[1]] <- acc(S[[o]][[1]], rowsum(sc, cl_code[[1]][i]))
      S[[o]][[2]] <- acc(S[[o]][[2]], rowsum(sc, cl_code[[2]][i]))
      S[[o]][[3]] <- acc(S[[o]][[3]], rowsum(sc, int_code[i]))
    }
  }
  meat <- function(M) { xy <- M %*% bread; crossprod(xy) }

  # ---- 6. small-sample corrections (fixest defaults; common to all outcomes) -
  G_min <- min(G)
  n_fe <- length(fe_sizes)
  K_raw <- K_coef + sum(fe_sizes) - (n_fe - 1L)             # object$nparams
  nested <- vapply(seq_len(n_fe), function(q)
    any(vapply(cl_code, function(g) fwl_is_nested(fe_code[[q]], g), TRUE)), TRUE)
  names(nested) <- names(fe_sizes)
  if (all(nested)) {
    K <- K_raw - (sum(fe_sizes) - (n_fe - 1L)) + 1L
  } else {
    K <- K_raw - (sum(fe_sizes[nested]) - sum(fe_sizes[nested] > 0))
  }
  K <- max(K, K_coef + 1L)
  adj_K <- (N - 1) / (N - K)
  df_t <- max(G_min - 1L, 1L)
  outs <- lapply(seq_len(Ky), function(o) {
    V <- meat(S[[o]][[1]]) + meat(S[[o]][[2]]) - meat(S[[o]][[3]])
    V <- V * G_min / (G_min - 1)                            # G.adj, G.df = "min"
    V <- V * adj_K                                          # K.adj
    dimnames(V) <- list(spec$name, spec$name)
    # non-PD fix (fixest:::mat_posdef_fix, replacement = 1e-16)
    ev <- eigen(V, symmetric = TRUE)
    fixed_flag <- any(ev$values <= 0); maxchg <- 0
    if (fixed_flag) {
      Vf <- tcrossprod(ev$vectors %*% diag(pmax(ev$values, 1e-16), nrow(V)), ev$vectors)
      maxchg <- max(abs(V - Vf)); dimnames(Vf) <- dimnames(V); V <- Vf
      warning(sprintf("[%s] The VCOV matrix is not positive definite and was 'fixed' (max change %.3g).", onames[o], maxchg), call. = FALSE)
    }
    beta <- setNames(as.numeric(B[, o]), spec$name)
    se <- sqrt(diag(V)); tval <- beta / se
    pval <- 2 * pt(-abs(tval), df = df_t)                   # t.df = "min"
    ct <- data.frame(Estimate = beta, `Std. Error` = se, `t value` = tval, `Pr(>|t|)` = pval,
                     check.names = FALSE, row.names = spec$name)
    list(coeftable = ct, vcov = V, vcov_fixed = fixed_flag, vcov_max_change = maxchg,
         ssr = ssr[o], sst = sst[[o]], r2 = 1 - ssr[o] / sst[[o]])
  })
  names(outs) <- onames
  vcov_s <- proc.time()[["elapsed"]] - t_v
  c(outs[[1]][c("coeftable", "vcov", "vcov_fixed", "ssr", "sst", "r2")],
    list(outcomes = outs, nobs = N, n_trips_est = wsum, n_singletons = n_single, K = K, K_raw = K_raw,
         K_coef = K_coef, fe_sizes = fe_sizes, nested = nested, adj_K = adj_K,
         adj_G = G_min / (G_min - 1), G = G, G_min = G_min, G_int = G_int, df_t = df_t,
         demean_s = demean_s, cross_s = cross_s, vcov_s = vcov_s,
         total_s = proc.time()[["elapsed"]] - t_all, spec = spec))
}

# stars with the project legend (*** 0.01, ** 0.05, * 0.10)
fwl_stars <- function(p) ifelse(p < 0.01, "***", ifelse(p < 0.05, "**", ifelse(p < 0.10, "*", "")))

# fwl_etable_tex(): etable-style bare-tabular .tex for an FWL fit (call wrap_for_beamer() after).
# dict maps bin variable -> row label; cluster_label is already LaTeX-escaped.
fwl_etable_tex <- function(fit, dict, tag, notes, path, fe_labels, cluster_label, dv_label = "driver\\_share") {
  tex_esc <- function(x) gsub("_", "\\_", x, fixed = TRUE)
  ct <- fit$coeftable
  var <- sub("::.*", "", rownames(ct)); lev <- sub(".*::", "", rownames(ct))
  lab <- paste0(dict[var], " $=$ ", lev)
  fmt <- function(x) formatC(x, format = "f", digits = 4)
  lines <- c("\\begingroup", "\\centering", "\\begin{tabular}{lc}",
             "   \\tabularnewline \\midrule \\midrule",
             sprintf("   Dependent Variable: & %s\\\\", dv_label),
             sprintf("   Sample: & %s \\\\", tex_esc(tag)),
             "   Model: & (1)\\\\", "   \\midrule", "   \\emph{Variables}\\\\")
  for (i in seq_along(lab)) {
    st <- fwl_stars(ct[["Pr(>|t|)"]][i])
    cell <- paste0(fmt(ct$Estimate[i]), if (nzchar(st)) paste0("$^{", st, "}$") else "")
    lines <- c(lines, sprintf("   %s & %s\\\\", lab[i], cell),
               sprintf("    & (%s)\\\\", fmt(ct[["Std. Error"]][i])))
  }
  lines <- c(lines, "   \\midrule", "   \\emph{Fixed-effects}\\\\",
             sprintf("   %s & Yes\\\\", tex_esc(fe_labels)),
             "   \\midrule", "   \\emph{Fit statistics}\\\\",
             sprintf("   Observations & %s\\\\", format(fit$nobs, big.mark = ",")),
             sprintf("   R$^2$ & %s\\\\", formatC(fit$r2, format = "f", digits = 5)),
             "   \\midrule \\midrule",
             sprintf("   \\multicolumn{2}{l}{\\emph{Clustered (%s) standard-errors in parentheses}}\\\\", cluster_label),
             "   \\multicolumn{2}{l}{\\emph{Signif. Codes: ***: 0.01, **: 0.05, *: 0.1}}\\\\",
             "\\end{tabular}", " ", "\\par \\raggedright ", tex_esc(notes), "\\par\\endgroup")
  writeLines(lines, path)
  invisible(path)
}

# fwl_etable_tex_multi(): same style, one column per outcome (fit$outcomes[[k]]).
# col_labels: DV header per column. Observations row uses the post-singleton N.
fwl_etable_tex_multi <- function(fit, dict, col_labels, tag, notes, path, fe_labels, cluster_label, digits = 4) {
  tex_esc <- function(x) gsub("_", "\\_", x, fixed = TRUE)
  outs <- fit$outcomes; nc <- length(outs)
  ct1 <- outs[[1]]$coeftable
  var <- sub("::.*", "", rownames(ct1)); lev <- sub(".*::", "", rownames(ct1))
  lab <- paste0(dict[var], " $=$ ", lev)
  fmt <- function(x) formatC(x, format = "f", digits = digits)
  amp <- function(v) paste(v, collapse = " & ")
  lines <- c("\\begingroup", "\\centering", sprintf("\\begin{tabular}{l%s}", strrep("c", nc)),
             "   \\tabularnewline \\midrule \\midrule",
             sprintf("   Dependent Variable: & %s\\\\", amp(col_labels)),
             sprintf("   Sample: & %s \\\\", amp(rep(tex_esc(tag), nc))),
             sprintf("   Model: & %s\\\\", amp(sprintf("(%d)", seq_len(nc)))), "   \\midrule", "   \\emph{Variables}\\\\")
  for (i in seq_along(lab)) {
    cells <- vapply(outs, function(o) {
      st <- fwl_stars(o$coeftable[["Pr(>|t|)"]][i])
      paste0(fmt(o$coeftable$Estimate[i]), if (nzchar(st)) paste0("$^{", st, "}$") else "")
    }, "")
    ses <- vapply(outs, function(o) sprintf("(%s)", fmt(o$coeftable[["Std. Error"]][i])), "")
    lines <- c(lines, sprintf("   %s & %s\\\\", lab[i], amp(cells)), sprintf("    & %s\\\\", amp(ses)))
  }
  lines <- c(lines, "   \\midrule", "   \\emph{Fixed-effects}\\\\",
             sprintf("   %s & %s\\\\", tex_esc(fe_labels), amp(rep("Yes", nc))),
             "   \\midrule", "   \\emph{Fit statistics}\\\\",
             sprintf("   Observations & %s\\\\", amp(rep(format(fit$nobs, big.mark = ","), nc))),
             sprintf("   R$^2$ & %s\\\\", amp(vapply(outs, function(o) formatC(o$r2, format = "f", digits = 5), ""))),
             "   \\midrule \\midrule",
             sprintf("   \\multicolumn{%d}{l}{\\emph{Clustered (%s) standard-errors in parentheses}}\\\\", nc + 1, cluster_label),
             sprintf("   \\multicolumn{%d}{l}{\\emph{Signif. Codes: ***: 0.01, **: 0.05, *: 0.1}}\\\\", nc + 1),
             "\\end{tabular}", " ", "\\par \\raggedright ", tex_esc(notes), "\\par\\endgroup")
  writeLines(lines, path)
  invisible(path)
}
