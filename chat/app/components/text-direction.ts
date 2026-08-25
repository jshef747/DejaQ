// Browsers' native `dir="auto"` picks direction from the first strong
// character only (Unicode P2/P3), which misreads a Hebrew sentence that opens
// with a Latin term or acronym ("REST API הוא ארכיטקטורה...") as LTR even
// though the sentence is overwhelmingly Hebrew. Counting script majority
// instead gets that case right without a language model, and still returns
// "auto" for text with no strong characters at all (numbers, punctuation),
// which is exactly what dir="auto" would already do with nothing to go on.
const RTL_CHARS = /[֐-׿؀-ۿ]/g;
const LTR_CHARS = /[A-Za-z]/g;

export function textDirection(text: string): "rtl" | "ltr" | "auto" {
  const rtl = text.match(RTL_CHARS)?.length ?? 0;
  const ltr = text.match(LTR_CHARS)?.length ?? 0;
  if (rtl === 0 && ltr === 0) return "auto";
  return rtl >= ltr ? "rtl" : "ltr";
}
