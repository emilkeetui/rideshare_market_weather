# ============================================================
# Script: make_dq_report_tables.py
# Purpose: Turn the clean_data/dq/ audit caches into the tables (.tex booktabs + .csv) and
#          figures (.png) used by docs/data_quality/hvfhv_data_quality.tex.
# Inputs: clean_data/dq/month_*_{num,ts,cat,rules}.parquet, daily_counts.parquet,
#         hourly_counts.parquet, footer_rows.csv, fullperiod_quantiles_{exact,approx}.parquet,
#         raw_data/hvfhv/tlc_aggregates/{fhv_base_aggregate_report_2v9c-2k7f,
#         tlc_industry_indicators_v6kb-cqej}.csv
# Outputs: output/sum/dq_*.tex, dq_*.csv ; output/fig/dq_*.png
# Timezone: all timestamps are naive local America/New_York wall-clock (TLC convention).
# Usage:   python make_dq_report_tables.py [--force]   (refuses to overwrite dq_* otherwise)
# Author: EK  Date: 2026-10-02
# ============================================================
import argparse
import calendar
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DQ = ROOT / "clean_data" / "dq"
SUM = ROOT / "output" / "sum"
FIG = ROOT / "output" / "fig"
AGG = ROOT / "raw_data" / "hvfhv" / "tlc_aggregates"
sys.path.insert(0, str(Path(__file__).parent))
from audit_hvfhv_quality import months, NUM_VARS, RAW_NUM, CATS, TS_COLS  # noqa: E402

PLATFORMS = ["Uber", "Lyft", "Via", "Juno", "other"]
PAL = {"Uber": "#222222", "Lyft": "#CC79A7", "Via": "#0072B2", "Juno": "#E69F00", "other": "#009E73", "ALL": "#555555"}
DERIVED_UNITS = {"wait_time": "sec", "fare_per_mile": "$/mi", "driver_share": "ratio",
                 "mean_speed_mph": "mi/h", "platform_margin": "$", "trip_time": "sec", "trip_miles": "mi"}
# Structural (by-design / not-collected) nulls, footnoted rather than called "missing"
STRUCTURAL = {"cbd_congestion_fee": "field first appears 2025-01",
              "airport_fee": "null-typed column in 2020-04 and 2020-10 files"}
# Fields whose missingness is platform- or period-specific (a reporting practice, not random gaps)
PLATFORM_SPECIFIC = ["on_scene_datetime", "originating_base_num", "access_a_ride_flag"]


def tex_escape(s):
    return str(s).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&").replace("<", r"\textless{}").replace(">", r"\textgreater{}")


def fmt(x, d=2):
    if pd.isna(x):
        return "--"
    if abs(x) >= 1e6:
        return f"{x:,.0f}"
    v = f"{x:,.{d}f}"
    return v[1:] if v.startswith("-") and float(v.replace(",", "")) == 0 else v


def write_tex(df, name, cols=None, colfmt=None, panels=None):
    """Bare booktabs tabular (no float) so \\input works in the report. df is already formatted strings."""
    cols = cols or list(df.columns)
    colfmt = colfmt or "l" + "r" * (len(cols) - 1)
    lines = [rf"\begin{{tabular}}{{{colfmt}}}", r"\toprule",
             " & ".join(tex_escape(c) if not c.startswith("\\") else c for c in cols) + r" \\", r"\midrule"]
    for i, r in df.iterrows():
        if panels and i in panels:
            lines.append(rf"\multicolumn{{{len(cols)}}}{{l}}{{\emph{{{panels[i]}}}}} \\")
        lines.append(" & ".join(tex_escape(v) for v in r[cols]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (SUM / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    df.to_csv(SUM / f"{name}.csv", index=False)


def load_cache(kind):
    return pd.concat([pd.read_parquet(DQ / f"month_{m}_{kind}.parquet") for m in months()], ignore_index=True)


def full_period_stats(num, quant):
    a = num[num.platform == "ALL"]
    g = a.groupby(["variable", "filtered"])
    s = g[["n_rows", "n_null", "n_nonnull", "sum", "sum_sq"]].sum()
    s["min"], s["max"] = g["min"].min(), g["max"].max()
    s["mean"] = s["sum"] / s["n_nonnull"]
    s["sd"] = np.sqrt((s["sum_sq"] - s["n_nonnull"] * s["mean"] ** 2) / (s["n_nonnull"] - 1))
    s["pct_missing"] = 100 * s["n_null"] / s["n_rows"]
    s = s.reset_index()
    if quant is not None:
        raw = quant[["variable", "median", "p01", "p99"]].assign(filtered=0)
        flt = quant[["variable", "median_f", "p01_f", "p99_f"]].rename(
            columns={"median_f": "median", "p01_f": "p01", "p99_f": "p99"}).assign(filtered=1)
        s = s.merge(pd.concat([raw, flt]), on=["variable", "filtered"], how="left")
    return s


def table_summary_full(stats, method):
    rows, panels = [], {}
    for flt, label in [(0, "Panel A: raw records, no filters"), (1, "Panel B: after CLAUDE.md cleaning filters")]:
        panels[len(rows)] = label
        for v in NUM_VARS:
            r = stats[(stats.variable == v) & (stats.filtered == flt)]
            if r.empty:
                continue
            r = r.iloc[0]
            rows.append({"Variable": v, "N": f"{int(r.n_nonnull):,}", "% missing": f"{r.pct_missing:.2f}",
                         "Mean": fmt(r["mean"]), "SD": fmt(r.sd), "Median": fmt(r.get("median", np.nan)),
                         "Min": fmt(r["min"]), "P1": fmt(r.get("p01", np.nan)), "P99": fmt(r.get("p99", np.nan)),
                         "Max": fmt(r["max"])})
    df = pd.DataFrame(rows)
    write_tex(df, "dq_summary_full", panels=panels)
    return df


def table_missing_by_year(num, ts, cat):
    a = num[(num.platform == "ALL") & (num.filtered == 0) & num.variable.isin(RAW_NUM)].copy()
    a["year"] = a.month.str[:4]
    rows = a.groupby(["variable", "year"])[["n_null", "n_rows"]].sum().reset_index()
    rows["pct"] = 100 * rows.n_null / rows.n_rows
    t = ts[ts.platform == "ALL"].copy()
    t["year"] = t.month.str[:4]
    t = t.groupby(["variable", "year"])[["n_null", "n_rows"]].sum().reset_index()
    t["pct"] = 100 * t.n_null / t.n_rows
    c = cat.copy()
    c["year"] = c.month.str[:4]
    c["miss"] = c.value.isna() | (c.value.fillna("x").str.strip() == "")
    tot = c.groupby(["variable", "year"]).n.sum()
    ms = c[c.miss].groupby(["variable", "year"]).n.sum()
    cc = pd.DataFrame({"n_rows": tot, "n_null": ms}).fillna(0).reset_index()
    cc["pct"] = 100 * cc.n_null / cc.n_rows
    allm = pd.concat([cc[["variable", "year", "pct"]], t[["variable", "year", "pct"]], rows[["variable", "year", "pct"]]])
    wide = allm.pivot(index="variable", columns="year", values="pct")
    order = CATS + TS_COLS + RAW_NUM
    wide = wide.reindex([v for v in order if v in wide.index])
    wide.to_csv(SUM / "dq_missing_by_year_numeric.csv")
    out = wide.map(lambda x: f"{x:.2f}").reset_index().rename(columns={"variable": "Variable"})
    out["Variable"] = [v + ("$^{\\dagger}$" if v in STRUCTURAL else "$^{\\ddagger}$" if v in PLATFORM_SPECIFIC else "")
                       for v in out["Variable"]]
    # write without escaping the dagger math: tex_escape leaves $ and ^ alone
    write_tex(out, "dq_missing_by_year")
    return wide


def table_missing_platform(ts, cat):
    """% missing (null or blank) for the platform-specific fields, by platform and year."""
    t = ts[ts.variable == "on_scene_datetime"].rename(columns={"n_null": "miss"})[["month", "platform", "variable", "n_rows", "miss"]]
    t = t[t.platform != "ALL"]
    c = cat[cat.variable.isin(["originating_base_num", "access_a_ride_flag"])].copy()
    c["miss"] = np.where(c.value.isna() | (c.value.fillna("x").str.strip() == ""), c.n, 0)
    c = c.groupby(["month", "platform", "variable"], as_index=False)[["n", "miss"]].sum().rename(columns={"n": "n_rows"})
    a = pd.concat([t, c])
    a["year"] = a.month.str[:4]
    g = a.groupby(["variable", "platform", "year"])[["miss", "n_rows"]].sum()
    g["pct"] = 100 * g.miss / g.n_rows
    g = g.reset_index()
    g.to_csv(SUM / "dq_missing_platform_numeric.csv", index=False)
    w = g.pivot_table(index=["variable", "platform"], columns="year", values="pct")
    out = w.map(lambda x: "--" if pd.isna(x) else f"{x:.1f}").reset_index()
    out.columns = ["Variable", "Platform"] + list(w.columns)
    write_tex(out, "dq_missing_platform", colfmt="ll" + "r" * len(w.columns))
    return g


def table_summary_by_year(num):
    a = num[(num.platform == "ALL") & (num.filtered == 0)].copy()
    a["year"] = a.month.str[:4]
    heads = ["base_passenger_fare", "trip_miles", "trip_time", "driver_pay", "tips", "wait_time",
             "fare_per_mile", "driver_share"]
    rows = []
    for v in heads:
        x = a[a.variable == v]
        for y, g in x.groupby("year"):
            w = g.n_nonnull
            rows.append({"variable": v, "year": y, "mean": g["sum"].sum() / w.sum(),
                         "median_wavg": np.average(g["median"], weights=w)})
    df = pd.DataFrame(rows)
    df.to_csv(SUM / "dq_summary_by_year_numeric.csv", index=False)
    piv = df.pivot(index="year", columns="variable", values=["mean", "median_wavg"])
    out = []
    for y in piv.index:
        r = {"Year": y}
        for v in heads:
            r[f"{v} mean"] = fmt(piv.loc[y, ("mean", v)])
            r[f"{v} med."] = fmt(piv.loc[y, ("median_wavg", v)])
        out.append(r)
    out = pd.DataFrame(out)
    # transpose: variables as rows is more readable
    t = out.set_index("Year").T.reset_index().rename(columns={"index": "Variable"})
    write_tex(t, "dq_summary_by_year")
    return df


def table_platform_year(num):
    a = num[(num.variable == "trip_miles") & (num.filtered == 0) & (num.platform != "ALL")].copy()
    a["year"] = a.month.str[:4]
    p = a.pivot_table(index="platform", columns="year", values="n_rows", aggfunc="sum").reindex(PLATFORMS).fillna(0)
    first_last = a[a.n_rows > 0].groupby("platform").month.agg(["min", "max"])
    out = p.map(lambda x: f"{int(x):,}").reset_index().rename(columns={"platform": "Platform"})
    out["First month"] = out.Platform.map(first_last["min"]).fillna("never")
    out["Last month"] = out.Platform.map(first_last["max"]).fillna("never")
    write_tex(out, "dq_trips_platform_year")
    a.pivot_table(index="platform", columns="month", values="n_rows", aggfunc="sum").to_csv(SUM / "dq_trips_platform_month.csv")
    return a


def table_out_of_range(rules):
    r = rules[rules.platform == "ALL"].copy()
    r["year"] = r.month.str[:4]
    cols = [c for c in r.columns if c not in ("month", "platform", "year")]
    y = r.groupby("year")[cols].sum()
    y.to_csv(SUM / "dq_out_of_range_counts.csv")
    keep = [c for c in cols if c not in ("n_rows",)]
    pct = y[keep].div(y.n_rows, axis=0) * 100
    out = pct.T.map(lambda x: f"{x:.3f}").reset_index().rename(columns={"index": "Rule (% of rows)"})
    out.loc[len(out)] = ["total rows"] + [f"{int(v):,}" for v in y.n_rows]
    write_tex(out, "dq_out_of_range")
    return y


def benchmark(num, cat):
    base = pd.read_csv(AGG / "fhv_base_aggregate_report_2v9c-2k7f.csv")
    base["month"] = base.year.astype(str) + "-" + base.month.astype(str).str.zfill(2)
    # base -> company from observed dispatching_base_num (modal platform)
    d = cat[cat.variable == "dispatching_base_num"].groupby(["value", "platform"]).n.sum().reset_index()
    mp = d.sort_values("n").groupby("value").tail(1).set_index("value").platform
    mp.rename("platform").reset_index().rename(columns={"value": "base"}).to_csv(SUM / "dq_base_to_platform.csv", index=False)
    # The aggregate report lists each HVFHS company under a company-level label (UBER, LYFT, VIA, JUNO),
    # not under its individual B-numbers; the base->platform map above is kept as a cross-reference.
    company = {"UBER": "Uber", "LYFT": "Lyft", "VIA": "Via", "JUNO": "Juno"}
    base = base[base.base_license_number.isin(company)].copy()
    base["platform"] = base.base_license_number.map(company)
    agg = base.groupby(["month", "platform"]).total_dispatched_trips.sum().rename("agg_trips").reset_index()
    rec = num[(num.variable == "trip_miles") & (num.filtered == 0) & (num.platform != "ALL")][["month", "platform", "n_rows"]]
    m = rec.merge(agg, on=["month", "platform"], how="left")
    m["pct_diff"] = 100 * (m.n_rows - m.agg_trips) / m.agg_trips
    m.to_csv(SUM / "dq_benchmark_monthly.csv", index=False)
    # industry indicators: HVFHS trips/day x days in month vs. total records
    ind = pd.read_csv(AGG / "tlc_industry_indicators_v6kb-cqej.csv")
    ind = ind[ind.license_class == "FHV - High Volume"].copy()
    ind["days"] = [calendar.monthrange(int(s[:4]), int(s[5:]))[1] for s in ind.month_year]
    ind["ind_trips"] = ind.trips_per_day * ind.days
    tot = rec.groupby("month").n_rows.sum().rename("rec_trips").reset_index()
    mi = tot.merge(ind[["month_year", "ind_trips"]].rename(columns={"month_year": "month"}), on="month", how="left")
    mi["pct_diff_ind"] = 100 * (mi.rec_trips - mi.ind_trips) / mi.ind_trips
    mi.to_csv(SUM / "dq_benchmark_industry_monthly.csv", index=False)
    # yearly summary
    m_ok = m.dropna(subset=["agg_trips"])  # months where the aggregate report has a row for that company
    ma = m_ok.groupby(m_ok.month.str[:4])[["n_rows", "agg_trips"]].sum()
    mi_ok = mi.dropna(subset=["ind_trips"])  # compare only months where the indicator exists
    mb = mi_ok.groupby(mi_ok.month.str[:4])[["rec_trips", "ind_trips"]].sum()
    yr = ma.join(mb)
    yr["pct_gap_base_agg"] = 100 * (yr.n_rows - yr.agg_trips) / yr.agg_trips
    yr["pct_gap_industry"] = 100 * (yr.rec_trips - yr.ind_trips) / yr.ind_trips
    yr.to_csv(SUM / "dq_benchmark_yearly.csv")
    out = yr.reset_index().rename(columns={"month": "Year"})
    out = pd.DataFrame({"Year": out.Year, "Records": out.n_rows.map(lambda x: f"{int(x):,}"),
                        "Base aggregate": out.agg_trips.map(lambda x: fmt(x, 0)),
                        "Gap (%)": out.pct_gap_base_agg.map(lambda x: fmt(x, 2)),
                        "Industry indicators": out.ind_trips.map(lambda x: fmt(x, 0)),
                        "Gap, ind. (%)": out.pct_gap_industry.map(lambda x: fmt(x, 2))})
    write_tex(out, "dq_benchmark")
    flag = pd.concat([m[m.pct_diff.abs() > 2].assign(source="base_aggregate", gap=lambda d: d.pct_diff)[["month", "platform", "source", "gap"]],
                      mi[mi.pct_diff_ind.abs() > 2].assign(platform="ALL", source="industry_indicators",
                                                          gap=lambda d: d.pct_diff_ind)[["month", "platform", "source", "gap"]]])
    flag.to_csv(SUM / "dq_benchmark_flagged_months.csv", index=False)
    return m, mi, yr


# Documented events used only to label dips as "explained". Anything not listed stays "unexplained".
EVENTS = [("2020-04-01", "2020-06-15", "COVID-19 pause / reopening ramp"),
          ("2020-06-01", "2020-06-07", "NYC curfew (2020-06-01 to 06-07)"),
          ("2020-08-04", "2020-08-05", "Tropical Storm Isaias"),
          ("2020-12-16", "2020-12-17", "Nor'easter"),
          ("2021-01-31", "2021-02-02", "Snowstorm"),
          ("2021-08-21", "2021-08-22", "Tropical Storm Henri"),
          ("2021-09-01", "2021-09-02", "Remnants of Hurricane Ida"),
          ("2022-01-29", "2022-01-30", "Nor'easter"),
          ("2022-12-23", "2022-12-25", "Winter Storm Elliott (storm/cold)"),
          ("2023-09-29", "2023-09-29", "Flash flooding (Tropical Storm Ophelia)"),
          ("2026-01-25", "2026-01-25", "Winter Storm Fern"),
          ("2026-02-22", "2026-02-23", "Blizzard / NYC travel ban")]


def explain(d):
    ds = pd.Timestamp(d)
    for a, b, lab in EVENTS:
        if pd.Timestamp(a) <= ds <= pd.Timestamp(b):
            return lab
    if ds.month == 12 and ds.day in (24, 25, 31) or (ds.month == 1 and ds.day == 1) or (ds.month == 7 and ds.day == 4):
        return "Holiday"
    return "unexplained"


def flagged_days(daily, hourly):
    rows = []
    for p in ["Uber", "Lyft", "Via", "Juno", "other", "ALL"]:
        s = daily if p == "ALL" else daily[daily.platform == p]
        s = s.groupby("date").n_trips.sum()
        s = s.reindex(pd.date_range("2020-04-01", "2026-07-31"), fill_value=0)
        med = s.rolling(29, center=True, min_periods=15).median()
        near = s.rolling(29, center=True, min_periods=1).max() > 0  # active in +-14 days
        low = (s < 0.5 * med) & (med > 0)
        zero = (s == 0) & near
        for d in s.index[low | zero]:
            rows.append({"date": d.date(), "platform": p, "n_trips": int(s[d]), "centered_median_28d": med[d],
                         "ratio": s[d] / med[d] if med[d] > 0 else np.nan,
                         "rule": "zero" if s[d] == 0 else "<50% of median", "explanation": explain(d)})
    f = pd.DataFrame(rows)
    f.to_csv(SUM / "dq_flagged_days_all.csv", index=False)
    city = hourly.groupby("datetime_hour").n_trips.sum()
    full = city.reindex(pd.date_range("2020-04-01", "2026-07-31 23:00", freq="h"), fill_value=0)
    zh = full[full == 0].reset_index().rename(columns={"index": "datetime_hour", 0: "n_trips"})
    zh["explanation"] = zh.datetime_hour.map(explain)
    zh.to_csv(SUM / "dq_zero_hours_citywide.csv", index=False)
    cw = f[(f.platform == "ALL")]
    tab = cw.assign(date=cw.date.astype(str), n_trips=cw.n_trips.map("{:,}".format),
                    ratio=cw.ratio.map(lambda x: fmt(x, 2)))[["date", "n_trips", "ratio", "rule", "explanation"]]
    tab.columns = ["Date", "Trips", "Ratio to median", "Rule", "Explanation"]
    write_tex(tab, "dq_flagged_days", colfmt="lrrll")
    return f, zh


def figures(num, rules, daily, flagged, bench_m, bench_i, wide):
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    # 1 monthly trips by platform + aggregate overlay
    a = num[(num.variable == "trip_miles") & (num.filtered == 0) & (num.platform != "ALL")]
    p = a.pivot_table(index="month", columns="platform", values="n_rows", aggfunc="sum").fillna(0)
    x = pd.to_datetime(p.index + "-01")
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    for pl in PLATFORMS:
        if pl in p and p[pl].sum() > 0:
            ax.plot(x, p[pl] / 1e6, color=PAL[pl], label=pl)
    ax.plot(x, p.sum(axis=1) / 1e6, color="#999999", lw=1.6, label="All platforms (records)")
    ag = bench_m.groupby("month").agg_trips.sum(min_count=1)
    ax.plot(pd.to_datetime(ag.index + "-01"), ag.values / 1e6, color="#D55E00", ls="--", lw=1, label="TLC base aggregate (sum)")
    ax.set_ylabel("Trips per month (millions)")
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(FIG / "dq_monthly_trips_platform.png", dpi=200)
    plt.close(fig)
    # 2 heatmap of % missing
    hm = wide.copy()
    cols = list(hm.columns)
    mm = []
    n = num[(num.platform == "ALL") & (num.filtered == 0) & num.variable.isin(RAW_NUM)]
    mm = (100 * n.pivot(index="variable", columns="month", values="n_null") / n.pivot(index="variable", columns="month", values="n_rows"))
    mm = mm.reindex([v for v in RAW_NUM if v in mm.index])
    fig, ax = plt.subplots(figsize=(8, 3.2))
    im = ax.imshow(mm.values, aspect="auto", cmap="Blues", vmin=0, vmax=100)
    ax.set_yticks(range(len(mm.index)))
    ax.set_yticklabels(mm.index)
    step = 6
    ax.set_xticks(range(0, len(mm.columns), step))
    ax.set_xticklabels(mm.columns[::step], rotation=90)
    fig.colorbar(im, ax=ax, label="% missing")
    fig.tight_layout()
    fig.savefig(FIG / "dq_missing_heatmap.png", dpi=200)
    plt.close(fig)
    # 3 daily citywide trips with flagged days
    c = daily.groupby("date").n_trips.sum()
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.plot(c.index, c.values / 1e3, color="#555555", lw=0.6)
    fc = flagged[(flagged.platform == "ALL")]
    fd = pd.to_datetime(fc.date)
    unex = fc.explanation == "unexplained"
    ax.scatter(fd[~unex.values], c.reindex(fd[~unex.values]).values / 1e3, s=8, color="#0072B2", label="flagged, explained")
    ax.scatter(fd[unex.values], c.reindex(fd[unex.values]).values / 1e3, s=10, color="#D55E00", label="flagged, unexplained")
    ax.set_ylabel("Citywide trips per day (thousands)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "dq_daily_trips_flagged.png", dpi=200)
    plt.close(fig)
    # 4 monthly median fare per mile and driver share
    fig, axs = plt.subplots(1, 2, figsize=(8, 3))
    for ax, v, lab in zip(axs, ["fare_per_mile", "driver_share"], ["Median fare per mile ($)", "Median driver share (pay / fare)"]):
        s = num[(num.variable == v) & (num.filtered == 0) & (num.platform != "ALL")]
        for pl in ["Uber", "Lyft", "Via"]:
            q = s[s.platform == pl]
            if len(q):
                ax.plot(pd.to_datetime(q.month + "-01"), q["median"], color=PAL[pl], label=pl)
        ax.set_ylabel(lab)
    axs[0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG / "dq_fare_share_medians.png", dpi=200)
    plt.close(fig)


def write_numbers(num, rules, ts, stats, a_platform, yr, bm, bi, flagged, zh, mp_g, cat, daily):
    """Every number quoted in the report prose is emitted here as a LaTeX macro (no hand-typed numbers)."""
    M = {}

    def pct(x, d=2):
        v = f"{x:.{d}f}"
        v = v[1:] if v.startswith("-") and float(v) == 0 else v
        return v + "\\%"

    r = rules[rules.platform == "ALL"]
    tot = r.n_rows.sum()
    M["dqNmonths"] = f"{r.month.nunique()}"
    M["dqTotalTrips"] = f"{int(tot):,}"
    for pl in PLATFORMS:
        q = a_platform[a_platform.platform == pl]
        nz = q[q.n_rows > 0].month
        M[f"dqTrips{pl.capitalize()}"] = f"{int(q.n_rows.sum()):,}"
        M[f"dqFirst{pl.capitalize()}"] = nz.min() if len(nz) else "never"
        M[f"dqLast{pl.capitalize()}"] = nz.max() if len(nz) else "never"
    vd = daily[(daily.platform == "Via") & (daily.n_trips > 0)].sort_values("date")
    big = vd[vd.n_trips >= 100]
    M["dqViaLastDay"] = str(big.date.max().date())
    M["dqViaAvgDaily"] = f"{int(round(big.tail(28).n_trips.mean())):,}"
    M["dqViaTailDays"] = f"{int(((vd.date > big.date.max())).sum())}"
    M["dqDupTotal"] = f"{int(r.n_exact_dups.sum()):,}"
    for k, col in [("FareLeZero", "fare_le0"), ("FareGtThousand", "fare_gt1000"), ("MilesLeZero", "miles_le0"),
                   ("MilesGtHundred", "miles_gt100"), ("TimeLeSixty", "time_le60s"), ("TimeGtSixH", "time_gt6h"),
                   ("DriverShareGtOne", "driver_share_gt1"), ("RequestAfterPickup", "request_after_pickup"),
                   ("DoUnknown", "do_264_265"), ("PuUnknown", "pu_264_265"), ("AarY", "access_a_ride_y"),
                   ("DriverPayNeg", "driver_pay_neg"), ("DropoffLePickup", "dropoff_le_pickup")]:
        M[f"dqPct{k}"] = pct(100 * r[col].sum() / tot, 3)
        M[f"dqN{k}"] = f"{int(r[col].sum()):,}"
    M["dqPctPassFilters"] = pct(100 * r.n_pass_filters.sum() / tot)
    M["dqPickupOutsideMonth"] = f"{int(r.pickup_outside_month.sum()):,}"
    ry = r.assign(year=r.month.str[:4]).groupby("year")[["n_rows", "n_pass_filters", "driver_share_gt1"]].sum()
    ps = 100 * ry.n_pass_filters / ry.n_rows
    ds = 100 * ry.driver_share_gt1 / ry.n_rows
    M["dqPassMin"], M["dqPassMinYear"] = pct(ps.min()), ps.idxmin()
    M["dqPassMax"], M["dqPassMaxYear"] = pct(ps.max()), ps.idxmax()
    M["dqDsGtOneMin"], M["dqDsGtOneMinYear"] = pct(ds.min()), ds.idxmin()
    M["dqDsGtOneMax"], M["dqDsGtOneMaxYear"] = pct(ds.max()), ds.idxmax()
    # missingness: full period, platform ALL, raw records
    mt = pd.concat([ts[ts.platform == "ALL"].groupby("variable")[["n_null", "n_rows"]].sum(),
                    num[(num.platform == "ALL") & (num.filtered == 0) & num.variable.isin(RAW_NUM)]
                    .groupby("variable")[["n_null", "n_rows"]].sum()])
    mt["pct"] = 100 * mt.n_null / mt.n_rows
    for v, k in [("on_scene_datetime", "OnScene"), ("airport_fee", "AirportFee"), ("cbd_congestion_fee", "Cbd")]:
        M[f"dqPctNull{k}"] = pct(mt.loc[v, "pct"])
    mpg = mp_g.set_index(["variable", "platform", "year"]).pct
    mpa = mp_g.groupby(["variable", "platform"])[["miss", "n_rows"]].sum()
    mpa["pct"] = 100 * mpa.miss / mpa.n_rows
    for v, vk in [("on_scene_datetime", "OnScene"), ("originating_base_num", "OrigBase"), ("access_a_ride_flag", "AarBlank")]:
        for pl in ["Uber", "Lyft", "Via"]:
            M[f"dqNull{vk}{pl}"] = pct(mpa.loc[(v, pl), "pct"], 1)
    pre = mp_g[(mp_g.variable == "on_scene_datetime") & (mp_g.platform == "Lyft") & (mp_g.year < "2025")]
    M["dqOnSceneLyftBefore"] = pct(100 * pre.miss.sum() / pre.n_rows.sum(), 1)
    M["dqOnSceneLyftYrA"] = pct(mpg.loc[("on_scene_datetime", "Lyft", "2025")], 1)
    M["dqOnSceneLyftYrB"] = pct(mpg.loc[("on_scene_datetime", "Lyft", "2026")], 1)
    cc = cat[(cat.variable == "access_a_ride_flag") & (cat.platform == "Uber") & (cat.value.fillna("x").str.strip() == "")]
    M["dqAarBlankLastMonth"] = cc.month.max()
    M["dqNAarBlank"] = f"{int(cc.n.sum()):,}"
    inc = mt.drop(index=[v for v in list(STRUCTURAL) + PLATFORM_SPECIFIC if v in mt.index])
    M["dqMaxIncidentalNull"] = pct(inc.pct.max())
    M["dqMaxIncidentalNullVar"] = inc.pct.idxmax().replace("_", "\\_")
    # benchmark
    M["dqBaseGapMin"], M["dqBaseGapMax"] = pct(yr.pct_gap_base_agg.min()), pct(yr.pct_gap_base_agg.max())
    M["dqIndGapMin"], M["dqIndGapMax"] = pct(yr.pct_gap_industry.min()), pct(yr.pct_gap_industry.max())
    M["dqNBaseFlagged"] = f"{int((bm.pct_diff.abs() > 2).sum())}"
    M["dqNBaseMonths"] = f"{int(bm.pct_diff.notna().sum())}"
    w = bm.loc[bm.pct_diff.abs().idxmax()]
    M["dqBaseWorstGap"], M["dqBaseWorstMonth"] = pct(w.pct_diff), f"{w.month} ({w.platform})"
    # flagged days
    fc = flagged[flagged.platform == "ALL"]
    M["dqNFlaggedCity"] = f"{len(fc)}"
    M["dqNFlaggedUnexplained"] = f"{int((fc.explanation == 'unexplained').sum())}"
    M["dqNZeroHours"] = f"{len(zh)}"
    ok = bi.dropna(subset=["pct_diff_ind"])
    M["dqIndMonths"] = f"{len(ok)}"
    M["dqIndFlagged"] = f"{int((ok.pct_diff_ind.abs() > 2).sum())}"
    wi = ok.loc[ok.pct_diff_ind.abs().idxmax()]
    M["dqIndWorstGap"], M["dqIndWorstMonth"] = pct(wi.pct_diff_ind), wi.month
    M["dqZeroHoursFirst"], M["dqZeroHoursLast"] = str(zh.datetime_hour.min()), str(zh.datetime_hour.max())
    M["dqZeroHoursExplained"] = f"{int((zh.explanation != 'unexplained').sum())}"
    for v, k in [("fare_per_mile", "FarePerMile"), ("driver_share", "DriverShare")]:
        m = stats[(stats.variable == v) & (stats.filtered == 1)]
        if len(m) and "median" in m:
            M[f"dqMedian{k}"] = f"{m['median'].iloc[0]:.2f}"
    lines = ["% generated by make_dq_report_tables.py -- do not edit"]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in M.items()]
    (SUM / "dq_numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    pd.Series(M).to_csv(SUM / "dq_numbers.csv", header=["value"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    SUM.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    existing = list(SUM.glob("dq_*")) + list(FIG.glob("dq_*"))
    if existing and not a.force:
        sys.exit(f"{len(existing)} dq_* outputs already exist; rerun with --force after confirming overwrite")
    num, rules, ts, cat = (load_cache(k) for k in ("num", "rules", "ts", "cat"))
    foot = pd.read_csv(DQ / "footer_rows.csv")
    chk = num[(num.variable == "trip_miles") & (num.filtered == 0) & (num.platform == "ALL")][["month", "n_rows"]].merge(foot, on="month")
    assert (chk.n_rows == chk.footer_rows).all(), "audit n_rows != parquet footer rows"
    print(f"row-count check OK: {chk.n_rows.sum():,} rows over {len(chk)} months equals parquet footers")
    quant = None
    fa, fe = DQ / "fullperiod_quantiles_approx.parquet", DQ / "fullperiod_quantiles_exact.parquet"
    if fa.exists():
        quant = pd.read_parquet(fa)
        if fe.exists():  # exact (quantile_cont over all files) overrides the t-digest for variables computed exactly
            ex = pd.read_parquet(fe)
            ex_vars = set(ex.variable)
            quant = pd.concat([quant[~quant.variable.isin(ex_vars)], ex], ignore_index=True)
            tdig = pd.read_parquet(fa).set_index("variable").loc[sorted(ex_vars)]
            ex.set_index("variable")[["median", "median_f"]].join(tdig[["median", "median_f"]], rsuffix="_tdigest") \
                .to_csv(SUM / "dq_median_exact_vs_tdigest.csv")
        print("full-period quantiles: t-digest; exact for", sorted(ex_vars) if fe.exists() else "none")
    elif fe.exists():
        quant = pd.read_parquet(fe)
    stats = full_period_stats(num, quant)
    stats.to_csv(SUM / "dq_summary_full_numeric.csv", index=False)
    table_summary_full(stats, None)
    wide = table_missing_by_year(num, ts, cat)
    mp_g = table_missing_platform(ts, cat)
    table_summary_by_year(num)
    a_platform = table_platform_year(num)
    table_out_of_range(rules)
    bm, bi, yr = benchmark(num, cat)
    daily = pd.read_parquet(DQ / "daily_counts.parquet")
    hourly = pd.read_parquet(DQ / "hourly_counts.parquet")
    flagged, zh = flagged_days(daily, hourly)
    figures(num, rules, daily, flagged, bm, bi, wide)
    write_numbers(num, rules, ts, stats, a_platform, yr, bm, bi, flagged, zh, mp_g, cat, daily)
    print(yr)
    print("flagged citywide days:", (flagged.platform == "ALL").sum(), " zero hours citywide:", len(zh))


if __name__ == "__main__":
    main()
