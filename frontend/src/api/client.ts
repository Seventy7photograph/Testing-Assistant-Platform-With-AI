import axios, { AxiosError } from "axios";

import type { ApiResponse } from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly detail: unknown;

  constructor(message: string, code = "ERROR", detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
  }
}

export const http = axios.create({
  baseURL: "/api/v1",
  timeout: 300_000,
});

interface ErrorBody {
  message?: string;
  code?: string;
  detail?: unknown;
}

function normalize(err: unknown): ApiError {
  const ax = err as AxiosError<ErrorBody>;
  if (ax?.response) {
    const body = ax.response.data;
    const message =
      (body && typeof body === "object" && body.message) ||
      `请求失败（HTTP ${ax.response.status}）`;
    const code =
      (body && typeof body === "object" && body.code) ||
      `HTTP_${ax.response.status}`;
    const detail = body && typeof body === "object" ? body.detail : null;
    return new ApiError(String(message), String(code), detail);
  }
  if (ax?.code === "ECONNABORTED") {
    return new ApiError(
      "请求超时。用例量大时生成耗时较长，请稍后重试或缩小解析条目上限。",
      "TIMEOUT",
    );
  }
  return new ApiError(
    "无法连接服务端。请确认后端已启动（python run.py）。",
    "NETWORK",
  );
}

export function unwrap<T>(res: ApiResponse<T>): T {
  if (!res || res.success !== true || res.data === null) {
    throw new ApiError(
      res?.message || "服务端返回了非预期的响应结构。",
      res?.code || "BAD_PAYLOAD",
      null,
    );
  }
  return res.data;
}

export async function get<T>(
  url: string,
  params?: Record<string, unknown>,
): Promise<T> {
  try {
    const res = await http.get<ApiResponse<T>>(url, { params });
    return unwrap(res.data);
  } catch (err) {
    throw normalize(err);
  }
}

export async function post<T>(
  url: string,
  body?: unknown,
  params?: Record<string, unknown>,
): Promise<T> {
  try {
    const res = await http.post<ApiResponse<T>>(url, body, { params });
    return unwrap(res.data);
  } catch (err) {
    throw normalize(err);
  }
}

export async function put<T>(url: string, body?: unknown): Promise<T> {
  try {
    const res = await http.put<ApiResponse<T>>(url, body);
    return unwrap(res.data);
  } catch (err) {
    throw normalize(err);
  }
}

export async function del<T>(url: string): Promise<T> {
  try {
    const res = await http.delete<ApiResponse<T>>(url);
    return unwrap(res.data);
  } catch (err) {
    throw normalize(err);
  }
}

export async function upload<T>(url: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file, file.name);
  try {
    const res = await http.post<ApiResponse<T>>(url, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return unwrap(res.data);
  } catch (err) {
    throw normalize(err);
  }
}

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

function filenameFromDisposition(header: string | undefined): string {
  if (!header) return "";
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8?.[1]) return decodeURIComponent(utf8[1]);
  const plain = header.match(/filename="?([^";]+)"?/i);
  return plain?.[1] ?? "";
}

export async function downloadFile(url: string): Promise<DownloadedFile> {
  try {
    const res = await http.get(url, { responseType: "blob" });
    return {
      blob: res.data as Blob,
      filename: filenameFromDisposition(
        res.headers["content-disposition"] as string | undefined,
      ),
    };
  } catch (err) {
    throw normalize(err);
  }
}

export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}
