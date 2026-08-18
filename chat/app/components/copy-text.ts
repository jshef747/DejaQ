"use client";

// navigator.clipboard exists only on a secure origin, and `start.sh --lan`
// serves the chat over plain http, so every copy control has to survive it
// being undefined as well as writeText rejecting on a denied permission.
// Returns whether the text actually reached the clipboard; never throws.
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection-based copy, which insecure origins allow.
  }
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  let area: HTMLTextAreaElement | null = null;
  try {
    area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area?.remove();
  }
}
