import "server-only";

async function assertUsable(response: Response): Promise<Response> {
  if (response.status === 401) {
    throw new Error("API request unauthorized — session may have expired");
  }
  if (response.status >= 500) {
    const fallback = `API server error: ${response.status} ${response.statusText}`;
    let detail: string | undefined;
    try {
      const body = await response.clone().json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail ? `${detail} (${response.status})` : fallback);
  }
  return response;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!BASE_URL) throw new Error("NEXT_PUBLIC_API_BASE_URL is required");

  // Dev-admin bypass: the backend grants a local dev-admin context and ignores
  // this token. There is no other auth path — /admin/v1/* is protected by
  // loopback binding, not by a credential.
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer dev-local",
      ...init.headers,
    },
  });

  return assertUsable(response);
}

export async function apiUpload(
  path: string,
  formData: FormData
): Promise<Response> {
  const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!BASE_URL) throw new Error("NEXT_PUBLIC_API_BASE_URL is required");

  // Same auth as apiFetch, but NO Content-Type header: the browser/undici must
  // set multipart/form-data itself so it can generate the boundary. Setting it
  // by hand breaks the upload.
  const response = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    body: formData,
    headers: { Authorization: "Bearer dev-local" },
  });

  return assertUsable(response);
}
