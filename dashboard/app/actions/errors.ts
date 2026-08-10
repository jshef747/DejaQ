"use server";

type ValidationError = { msg?: unknown };

function flattenValidationDetail(detail: ValidationError[]) {
  const messages = detail
    .map((item) => (typeof item?.msg === "string" ? item.msg.replace(/^Value error, /, "") : ""))
    .filter(Boolean);
  return messages.length > 0 ? messages.join("; ") : null;
}

export async function responseErrorMessage(res: Response, fallback: string) {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") msg = body.detail;
    // FastAPI request-validation failures carry a list of error objects, not a
    // string, so without this every Pydantic-rejected save shows only the
    // generic fallback instead of the reason.
    else if (Array.isArray(body?.detail)) msg = flattenValidationDetail(body.detail) ?? msg;
    else if (typeof body?.message === "string") msg = body.message;
  } catch {}
  return msg;
}
