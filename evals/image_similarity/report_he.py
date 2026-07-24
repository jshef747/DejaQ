"""Hebrew, RTL-correct HTML report for the image-similarity clustering run.

Handles the two classic RTL correctness pitfalls:
- Mixed Hebrew/English/numeric content: every filename, model name, and number
  embedded in Hebrew prose is wrapped in <bdi>, which isolates it from the
  surrounding right-to-left run so word order and punctuation don't get
  scrambled by the Unicode bidi algorithm.
- Directional glyphs (arrows, etc.): avoided entirely in favor of plain
  Hebrew connector words, sidestepping Unicode's automatic mirroring of
  bidi-mirrored characters inside an RTL embedding.
"""
from __future__ import annotations

import html
from pathlib import Path


def _bdi(text, cls: str = "") -> str:
    escaped = html.escape(str(text))
    cls_attr = f' class="{cls}"' if cls else ""
    return f"<bdi{cls_attr}>{escaped}</bdi>"


def _fmt_pct(x: float) -> str:
    return _bdi(f"{x * 100:.1f}%")


def _fmt_dist(x: float) -> str:
    return _bdi(f"{x:.4f}")


def _thumb(rel_path: str, caption: str) -> str:
    return (
        "<figure>"
        f'<img src="{html.escape(rel_path)}" loading="lazy" alt="{html.escape(caption)}">'
        f"<figcaption>{_bdi(caption, 'mono')}</figcaption>"
        "</figure>"
    )


_CSS = """
  :root { color-scheme: light dark; }
  body {
    direction: rtl; text-align: right; font-family: "Arial Hebrew", Arial, "Segoe UI", sans-serif;
    max-width: 1000px; margin: 30px auto; padding: 0 16px; line-height: 1.6;
  }
  h1 { font-size: 26px; margin-bottom: 4px; }
  h2 { font-size: 19px; margin-top: 34px; border-bottom: 2px solid #ccc; padding-bottom: 6px; }
  h3 { font-size: 15px; margin: 0 0 8px; }
  .meta, .explain { color: #555; font-size: 14px; }
  .privacy { color: #2a7a2a; font-size: 13px; }
  .hint { font-weight: normal; color: #888; font-size: 14px; }
  bdi.mono { font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
  bdi.badge { background: #eee; border-radius: 4px; padding: 1px 6px; margin-inline-end: 4px; display: inline-block; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }
  .stat { background: #f4f4f4; border-radius: 8px; padding: 14px; text-align: center; }
  .stat .value { font-size: 24px; font-weight: bold; }
  .stat .label { font-size: 13px; color: #555; margin-top: 4px; }
  .cluster.problem { border: 1px solid #d9534f; border-radius: 8px; padding: 12px; margin-bottom: 14px; background: #fff6f6; }
  .thumbs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .thumbs figure { margin: 0; text-align: center; width: 104px; }
  .thumbs img { width: 100px; height: 100px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc; }
  .thumbs figcaption { font-size: 10px; word-break: break-all; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: right; }
  th { background: #f4f4f4; }
  tr.highlight td { background: #fff8d6; font-weight: bold; }
  @media (prefers-color-scheme: dark) {
    body { background: #1c1c1e; color: #eee; }
    .stat { background: #2c2c2e; }
    .stat .label { color: #aaa; }
    bdi.badge { background: #3a3a3c; }
    th { background: #2c2c2e; }
    th, td { border-color: #444; }
    h2 { border-color: #444; }
    .cluster.problem { background: #3a1f1f; border-color: #a94442; }
    .meta, .explain { color: #bbb; }
    tr.highlight td { background: #4a4322; }
  }
"""


def _html_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def write_report(
    *,
    out_dir: Path,
    input_dir: Path,
    valid_paths: list[Path],
    labels: list[int],
    threshold: float,
    cluster_info: list[dict],
    n_singles: int,
    nearest: list[tuple[int, int, float]],
    gt_scores: dict | None,
) -> Path:
    n = len(valid_paths)

    # index -> path relative to out_dir, for <img src>
    rel_path: dict[int, str] = {}
    for c in cluster_info:
        for idx in c["indices"]:
            rel_path[idx] = f"cluster_{c['num']:02d}/{valid_paths[idx].name}"
    for idx in range(n):
        if idx not in rel_path:
            rel_path[idx] = f"singletons/{valid_paths[idx].name}"

    sections = [f"""
    <h1>דוח בדיקת דמיון תמונות</h1>
    <p class="meta">
      בדיקת סף ההתאמה למטמון תמונות (fingerprint gate) באמצעות מודל
      {_bdi("CLIP ViT-B/32", "mono")}.
      תיקיית מקור: {_bdi(str(input_dir), "mono")}.
      סף מרחק (threshold): {_fmt_dist(threshold)}.
    </p>
    <p class="privacy">העיבוד בוצע כולו במחשב המקומי; התמונות לא הועלו לשום שרת חיצוני.</p>
    """]

    cards = [
        ("סה״כ תמונות", str(n)),
        ("אשכולות (2+ תמונות)", str(len(cluster_info))),
        ("תמונות בודדות (ללא התאמה)", str(n_singles)),
    ]
    if gt_scores:
        cards.append(("ריקול ממוצע", _fmt_pct(gt_scores["avg_recall"])))
        cards.append(("טוהר משוקלל", _fmt_pct(gt_scores["weighted_purity"])))

    cards_html = "".join(
        f'<div class="stat"><div class="value">{v}</div><div class="label">{k}</div></div>'
        for k, v in cards
    )
    sections.append(f'<div class="stat-grid">{cards_html}</div>')

    if gt_scores:
        sections.append("""
        <p class="explain">
          <b>ריקול</b>: אחוז הווריאציות (עותקים דומים של אותה תמונת מקור) שנשארו יחד
          עם התמונה המקורית שלהן באותו אשכול.
          <b>טוהר</b>: אחוז התמונות בכל אשכול שבאמת שייכות לאותה תמונת מקור,
          כלומר אין מיזוג שגוי של תמונות שונות.
        </p>
        """)

    if gt_scores and gt_scores["split_groups"]:
        items = []
        for g in sorted(gt_scores["split_groups"], key=lambda x: x["recall"]):
            thumbs = "".join(_thumb(rel_path[i], valid_paths[i].name) for i in g["indices"])
            items.append(f"""
            <div class="cluster problem">
              <h3>קבוצה {_bdi(g['group'], 'mono')} — ריקול {_fmt_pct(g['recall'])}</h3>
              <div class="thumbs">{thumbs}</div>
            </div>
            """)
        sections.append(
            "<h2>קבוצות שהתפצלו <span class=\"hint\">(הסף מחמיר מדי עבור זוגות אלו)</span></h2>"
            + "".join(items)
        )

    if gt_scores and gt_scores["mixed_clusters"]:
        items = []
        for m in gt_scores["mixed_clusters"]:
            badges = " ".join(_bdi(f"{k}: {v}", "mono badge") for k, v in m["counts"].items())
            thumbs = "".join(_thumb(rel_path[i], valid_paths[i].name) for i in m["indices"])
            items.append(f"""
            <div class="cluster problem">
              <h3>אשכול מעורב — {badges}</h3>
              <div class="thumbs">{thumbs}</div>
            </div>
            """)
        sections.append(
            "<h2>אשכולות שמיזגו תמונות ממקורות שונים "
            "<span class=\"hint\">(הסף מקל מדי עבור זוגות אלו)</span></h2>"
            + "".join(items)
        )

    row_list = []
    for c in sorted(cluster_info, key=lambda c: -len(c["indices"])):
        num, size = c["num"], len(c["indices"])
        row_list.append(
            f"<tr><td>{_bdi(f'#{num:02d}')}</td><td>{_bdi(size)}</td>"
            f"<td>{_fmt_dist(c['max_dist'])}</td></tr>"
        )
    sections.append(f"""
    <h2>טבלת כל האשכולות</h2>
    <table>
      <thead><tr><th>מספר אשכול</th><th>גודל</th><th>מרחק מקסימלי בתוך האשכול</th></tr></thead>
      <tbody>{''.join(row_list)}</tbody>
    </table>
    """)

    cross = sorted((t for t in nearest if labels[t[0]] != labels[t[1]]), key=lambda t: t[2])
    watch_rows = []
    for i, j, d in cross[:20]:
        watch_rows.append(
            f"<tr><td>{_bdi(valid_paths[i].name, 'mono')}</td>"
            f"<td>{_bdi(valid_paths[j].name, 'mono')}</td>"
            f"<td>{_fmt_dist(d)}</td></tr>"
        )
    if watch_rows:
        sections.append(f"""
        <h2>הזוגות הקרובים ביותר בין אשכולות שונים <span class="hint">(לכיוונון הסף)</span></h2>
        <table>
          <thead><tr><th>תמונה א׳</th><th>תמונה ב׳</th><th>מרחק</th></tr></thead>
          <tbody>{''.join(watch_rows)}</tbody>
        </table>
        """)

    body = "\n".join(sections)
    report_path = out_dir / "report.html"
    report_path.write_text(_html_shell("דוח בדיקת דמיון תמונות", body), encoding="utf-8")
    return report_path


def write_sweep_report(*, out_path: Path, input_dir: Path, n_images: int, rows: list[dict]) -> Path:
    """Comparison table across multiple thresholds (recall/purity trade-off)."""
    has_gt = rows and rows[0]["recall"] is not None

    row_html = []
    for r in rows:
        recall_cell = _fmt_pct(r["recall"]) if has_gt else "—"
        purity_cell = _fmt_pct(r["purity"]) if has_gt else "—"
        split_cell = _bdi(r["n_split"]) if has_gt else "—"
        mixed_cell = _bdi(r["n_mixed"]) if has_gt else "—"
        row_html.append(
            f"<tr><td>{_fmt_dist(r['threshold'])}</td><td>{_bdi(r['n_clusters'])}</td>"
            f"<td>{recall_cell}</td><td>{purity_cell}</td>"
            f"<td>{split_cell}</td><td>{mixed_cell}</td></tr>"
        )

    body = f"""
    <h1>השוואת ערכי סף — בדיקת דמיון תמונות</h1>
    <p class="meta">
      תיקיית מקור: {_bdi(str(input_dir), "mono")}.
      סה״כ תמונות: {_bdi(n_images)}.
      מודל: {_bdi("CLIP ViT-B/32", "mono")}.
    </p>
    <p class="privacy">העיבוד בוצע כולו במחשב המקומי; התמונות לא הועלו לשום שרת חיצוני.</p>

    <p class="explain">
      <b>ריקול</b>: אחוז הווריאציות שנשארו יחד עם התמונה המקורית שלהן (סף נמוך מדי → ריקול יורד).
      <b>טוהר</b>: אחוז התמונות בכל אשכול שבאמת שייכות לאותה תמונת מקור (סף גבוה מדי → טוהר יורד).
      ככל שהסף עולה, הריקול נוטה לעלות והטוהר נוטה לרדת — זהו טרייד-אוף.
    </p>

    <h2>טבלת השוואה</h2>
    <table>
      <thead><tr>
        <th>סף מרחק</th><th>מס׳ אשכולות</th><th>ריקול</th><th>טוהר</th>
        <th>קבוצות מפוצלות</th><th>אשכולות מעורבים</th>
      </tr></thead>
      <tbody>{''.join(row_html)}</tbody>
    </table>
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_html_shell("השוואת ערכי סף", body), encoding="utf-8")
    return out_path


_VERDICT_HE = {"ACCEPT": "התקבל (VALID)", "REJECT": "נדחה (INVALID)"}


def write_validation_report(
    *,
    out_path: Path,
    input_dir: Path,
    results: list[dict],
    cross_reject_rate: float | None,
    same_accept_rate: float | None,
    latencies: list[float],
    caption_model: str,
    validator_model: str,
) -> Path:
    """Report for the caption+validator safeguard test (validate_pairs.py).
    Images referenced relative to out_path's own folder (they live alongside it)."""
    n_correct = sum(1 for r in results if r["correct"])
    mean_latency = sum(latencies) / len(latencies) if latencies else None

    cards = [
        ("סה״כ זוגות שנבדקו", str(len(results))),
        ("תוצאות תואמות לציפייה", f"{n_correct}/{len(results)}"),
    ]
    if cross_reject_rate is not None:
        cards.append(("שיעור דחיית מיזוגים שגויים", _fmt_pct(cross_reject_rate)))
    if same_accept_rate is not None:
        cards.append(("שיעור קבלת התאמות תקינות", _fmt_pct(same_accept_rate)))
    if mean_latency is not None:
        cards.append(("זמן כיתוב ממוצע", f"{mean_latency:.0f} ms"))

    cards_html = "".join(
        f'<div class="stat"><div class="value">{v}</div><div class="label">{k}</div></div>'
        for k, v in cards
    )

    # mismatches first, then by distance
    ordered = sorted(results, key=lambda r: (r["correct"], r["distance"]))

    pair_cards = []
    for r in ordered:
        css_class = "cluster problem" if not r["correct"] else "cluster"
        expected_he = _VERDICT_HE[r["expected"]]
        verdict_he = _VERDICT_HE[r["verdict"]]
        status = "התאמה" if r["correct"] else "אי-התאמה"
        thumbs = _thumb(r["path_i"].name, r["path_i"].name) + _thumb(r["path_j"].name, r["path_j"].name)
        pair_cards.append(f"""
        <div class="{css_class}">
          <h3>{_bdi(status)} — מרחק {_fmt_dist(r['distance'])} — צפוי: {expected_he} — התקבל: {verdict_he}</h3>
          <div class="thumbs">{thumbs}</div>
          <p class="explain">כיתוב תמונה 1: {_bdi(r['cap_i'])}</p>
          <p class="explain">כיתוב תמונה 2: {_bdi(r['cap_j'])}</p>
        </div>
        """)

    body = f"""
    <h1>דוח בדיקת אימות תמונות — כיתוב + שופט טקסט</h1>
    <p class="meta">
      תיקיית מקור: {_bdi(str(input_dir), "mono")}.
      מודל כיתוב: {_bdi(caption_model, "mono")}.
      מודל שופט: {_bdi(validator_model, "mono")}.
    </p>
    <p class="privacy">העיבוד בוצע כולו במחשב המקומי; התמונות לא הועלו לשום שרת חיצוני.</p>

    <p class="explain">
      עבור כל זוג תמונות במרחק "אזור אפור" (לא זהות אך לא רחוקות מדי), מודל הראייה מתאר כל
      תמונה במילים, ואז אותו שופט טקסט המשמש היום לאימות תשובות מהמטמון מחליט אם התיאורים
      מתארים את אותו הדבר. זוגות מ"קבוצות" מקור שונות (<b>צפוי: נדחה</b>) הן המיזוגים השגויים
      שהתגלו במבחן הדמיון התמונתי הטהור — הבדיקה כאן היא האם השופט תופס אותם. זוגות מאותה
      קבוצת מקור (<b>צפוי: התקבל</b>) הן התאמות לגיטימיות (חיתוך, סיבוב, צילום חוזר) שאסור
      לשופט לפסול בטעות.
    </p>

    <div class="stat-grid">{cards_html}</div>

    <h2>זוגות שנבדקו</h2>
    {''.join(pair_cards)}
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_html_shell("דוח בדיקת אימות תמונות", body), encoding="utf-8")
    return out_path


def write_phash_report(
    *,
    out_path: Path,
    input_dir: Path,
    pairs: list[dict],
    sweep_rows: list[dict],
    recommended_threshold: int,
    mean_hash_ms: float,
    by_variant: dict[str, list[bool]],
) -> Path:
    """Report for the dHash gate experiment (phash_gate.py)."""
    best_row = next(r for r in sweep_rows if r["threshold"] == recommended_threshold)
    n_correct = sum(1 for p in pairs if p["correct"])

    cards = [
        ("סה״כ זוגות שנבדקו", str(len(pairs))),
        ("סף מומלץ (מרחק המינג)", str(recommended_threshold)),
        ("שיעור דחיית מיזוגים שגויים", _fmt_pct(best_row["cross_reject"])),
        ("שיעור קבלת התאמות תקינות", _fmt_pct(best_row["same_accept"])),
        ("זמן חישוב טביעת אצבע ממוצע", f"{mean_hash_ms:.2f} ms"),
        ("תוצאות תואמות לציפייה", f"{n_correct}/{len(pairs)}"),
    ]
    cards_html = "".join(
        f'<div class="stat"><div class="value">{v}</div><div class="label">{k}</div></div>'
        for k, v in cards
    )

    sweep_rows_html = "".join(
        (f'<tr class="highlight">' if r["threshold"] == recommended_threshold else "<tr>")
        + f"<td>{_bdi(r['threshold'])}</td><td>{_fmt_pct(r['cross_reject'])}</td>"
        f"<td>{_fmt_pct(r['same_accept'])}</td></tr>"
        for r in sweep_rows
    )

    variant_rows = "".join(
        f"<tr><td>{_bdi(variant, 'mono')}</td><td>{_bdi(f'{sum(results)}/{len(results)}')}</td>"
        f"<td>{_fmt_pct(sum(results) / len(results))}</td></tr>"
        for variant, results in sorted(by_variant.items())
    )

    ordered = sorted(pairs, key=lambda p: (p["correct"], p["distance"]))
    pair_cards = []
    for p in ordered:
        css_class = "cluster problem" if not p["correct"] else "cluster"
        expected_he = _VERDICT_HE[p["expected"]]
        verdict_he = _VERDICT_HE[p["verdict"]]
        status = "התאמה" if p["correct"] else "אי-התאמה"
        thumbs = _thumb(p["path_i"].name, p["path_i"].name) + _thumb(p["path_j"].name, p["path_j"].name)
        pair_cards.append(f"""
        <div class="{css_class}">
          <h3>{_bdi(status)} — מרחק CLIP {_fmt_dist(p['distance'])} — מרחק המינג {_bdi(p['hamming'])}
              — צפוי: {expected_he} — התקבל: {verdict_he}</h3>
          <div class="thumbs">{thumbs}</div>
        </div>
        """)

    body = f"""
    <h1>דוח שער טביעת אצבע תפיסתית (pHash)</h1>
    <p class="meta">
      תיקיית מקור: {_bdi(str(input_dir), "mono")}.
      שיטה: {_bdi("dHash (Pillow, ללא תלות חדשה)", "mono")}.
    </p>
    <p class="privacy">העיבוד בוצע כולו במחשב המקומי; התמונות לא הועלו לשום שרת חיצוני.</p>

    <p class="explain">
      במקום לתאר תמונות במילים (איטי, ~4.5 שניות לתמונה, ולא תמיד עקבי — ראו הדוח הקודם),
      טביעת אצבע תפיסתית משווה את מבנה הפיקסלים ישירות: שינוי גודל, דחיסה מחדש או בהירות
      משאירים את הטביעה כמעט זהה, אך תמונה אחרת לגמרי — גם אם היא נראית דומה סמנטית (כמו שני
      קווי רקיע של ערים שונות) — מקבלת טביעה שונה מאוד. <b>סיבוב (rot3) אינו משתמר בשיטה זו
      במכוון</b> — טביעת אצבע מבוססת-גרדיאנט רגישה לסיבוב, כך שזוגות מסובבים עלולים להיכשל
      בשער ולהפוך לפספוס מטמון רגיל (עלות מקובלת).
    </p>

    <div class="stat-grid">{cards_html}</div>

    <h2>טבלת סריקת סף (מרחק המינג)</h2>
    <table>
      <thead><tr><th>סף (≤)</th><th>שיעור דחיית מיזוגים שגויים</th><th>שיעור קבלת התאמות תקינות</th></tr></thead>
      <tbody>{sweep_rows_html}</tbody>
    </table>

    <h2>שיעור קבלה לפי סוג וריאציה</h2>
    <table>
      <thead><tr><th>וריאציה</th><th>יחס</th><th>אחוז</th></tr></thead>
      <tbody>{variant_rows}</tbody>
    </table>

    <h2>זוגות שנבדקו (בסף המומלץ)</h2>
    {''.join(pair_cards)}
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_html_shell("דוח שער pHash", body), encoding="utf-8")
    return out_path
