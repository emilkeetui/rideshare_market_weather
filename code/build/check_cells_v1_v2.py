# ============================================================
# Script: check_cells_v1_v2.py
# Purpose: Verify the v2 OD cells (adds sum_log_fare, sum_log_pay) are identical to v1 on
#          everything v1 has: row count, keys, n_trips, sum_driver_share and the other sums.
#          Keys are joined (v1 FULL JOIN v2) so row order cannot matter.
# Inputs: clean_data/od_weather_cells_2021/cells_2021-MM.parquet (v1, read only)
#         clean_data/od_weather_cells_2021_v2/cells_2021-MM.parquet (v2, read only)
# Outputs: output/sum/od_cells_v1_v2_check.csv
# Author: EK  Date: 2026-10-01
# ============================================================
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V1, V2 = ROOT / "clean_data" / "od_weather_cells_2021", ROOT / "clean_data" / "od_weather_cells_2021_v2"
months = sys.argv[1].split(",") if len(sys.argv) > 1 else [f"{m:02d}" for m in range(1, 13)]
# pu_hod/do_hod (naive wall-clock hours) disambiguate the 38 March DST cells whose tz-aware keys collide
KEYS = ["platform", "pu_zone_id", "do_zone_id", "datetime_hour", "do_datetime_hour", "pu_hod", "do_hod"]
SUMS = ["n_trips", "sum_driver_share", "sum_fare", "sum_driver_pay", "sum_trip_miles", "sum_trip_time"]
OTHER = ["pu_precip_mm", "do_precip_mm", "month", "dow", "doy", "date"]
con = duckdb.connect()
rows = []
for mm in months:
    f1, f2 = (V1 / f"cells_2021-{mm}.parquet").as_posix(), (V2 / f"cells_2021-{mm}.parquet").as_posix()
    n1 = con.execute(f"SELECT count(*) FROM read_parquet('{f1}')").fetchone()[0]
    n2 = con.execute(f"SELECT count(*) FROM read_parquet('{f2}')").fetchone()[0]
    on = " AND ".join([f"a.{k} IS NOT DISTINCT FROM b.{k}" for k in KEYS])
    diffs = ", ".join([f"max(abs(a.{c} - b.{c})) AS d_{c}" for c in SUMS])
    neq = " + ".join([f"sum(CASE WHEN a.{c} IS DISTINCT FROM b.{c} THEN 1 ELSE 0 END)" for c in OTHER])
    q = f"""SELECT count(*) AS n_join, sum(CASE WHEN a.platform IS NULL OR b.platform IS NULL THEN 1 ELSE 0 END) AS n_unmatched,
                   {diffs}, {neq} AS n_other_neq
            FROM read_parquet('{f1}') a FULL JOIN read_parquet('{f2}') b ON {on}"""
    r = con.execute(q).fetchdf().iloc[0].to_dict()
    tot = con.execute(f"SELECT sum(n_trips), sum(sum_driver_share) FROM read_parquet('{f1}')").fetchone()
    tot2 = con.execute(f"SELECT sum(n_trips), sum(sum_driver_share), min(sum_log_fare), min(sum_log_pay), sum(CASE WHEN isfinite(sum_log_fare) AND isfinite(sum_log_pay) THEN 0 ELSE 1 END) FROM read_parquet('{f2}')").fetchone()
    # exact dup-key check on v2 keys
    dups = con.execute(f"SELECT count(*) - count(DISTINCT ({', '.join(KEYS)})) FROM read_parquet('{f2}')").fetchone()[0]
    row = {"month": mm, "rows_v1": n1, "rows_v2": n2, "n_join": int(r["n_join"]), "n_unmatched": int(r["n_unmatched"]),
           "sum_n_trips_v1": tot[0], "sum_n_trips_v2": tot2[0], "sum_driver_share_v1": tot[1], "sum_driver_share_v2": tot2[1],
           **{k: r[k] for k in r if k.startswith("d_")}, "n_other_neq": int(r["n_other_neq"]),
           "n_nonfinite_logs_v2": tot2[4], "dup_keys_v2": dups}
    ok = (n1 == n2 == row["n_join"] and row["n_unmatched"] == 0 and tot[0] == tot2[0] and row["n_other_neq"] == 0
          and tot2[4] == 0 and dups == 0 and row["d_n_trips"] == 0
          and all(row[f"d_{c}"] <= 1e-9 for c in SUMS))  # float sums: parallel summation order may differ at ~1e-13
    row["identical"] = bool(ok)
    rows.append(row)
    print(mm, "IDENTICAL" if ok else "DIFFERENT", {k: row[k] for k in ("rows_v1", "rows_v2", "n_unmatched", "n_other_neq")},
          "max abs diffs:", {c: row[f"d_{c}"] for c in SUMS})
out = ROOT / "output" / "sum" / "od_cells_v1_v2_check.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print("written", out)
if not all(r["identical"] for r in rows):
    sys.exit(1)
