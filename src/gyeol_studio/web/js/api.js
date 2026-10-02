// JSON API client: adds the current user, turns error responses into ApiError with the server's Korean message.
import { store } from "./store.js";

export class ApiError extends Error {
  constructor(message, code, detail, status) {
    super(message);
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function request(method, path, { json, form, signal } = {}) {
  const headers = {};
  const user = store.userId();
  if (user) headers["X-User"] = user;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body, signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("앱 서버에 연결할 수 없어요. 앱(결 스튜디오)이 켜져 있는지, 같은 와이파이에 연결되어 있는지 확인해 주세요.", "offline", String(e), 0);
  }
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (data && data.error) || {};
    if (res.status === 401 && err.code === "no_user") store.setUser(null);
    throw new ApiError(err.message || "처리하는 중에 문제가 생겼어요. 다시 시도해 주세요.", err.code || "http", err.detail || "", res.status);
  }
  return data;
}

export const api = {
  get: (p, o) => request("GET", p, o),
  post: (p, json, o) => request("POST", p, { ...o, json: json ?? {} }),
  patch: (p, json) => request("PATCH", p, { json }),
  put: (p, json) => request("PUT", p, { json }),
  del: (p, json) => request("DELETE", p, json !== undefined ? { json } : {}),
  upload: (p, form) => request("POST", p, { form }),
};

// Upload with progress (fetch has no upload progress): XMLHttpRequest.
export function uploadWithProgress(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    const user = store.userId();
    if (user) xhr.setRequestHeader("X-User", user);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else {
        const err = (data && data.error) || {};
        reject(new ApiError(err.message || "올리지 못했어요. 다시 시도해 주세요.", err.code || "http", err.detail || "", xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError("앱 서버에 연결할 수 없어요. 앱이 켜져 있는지 확인해 주세요.", "offline", "", 0));
    xhr.send(form);
  });
}
