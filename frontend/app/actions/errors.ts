"use server";

export async function responseErrorMessage(res: Response, fallback: string) {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") msg = body.detail;
    else if (typeof body?.message === "string") msg = body.message;
  } catch {}
  return msg;
}
