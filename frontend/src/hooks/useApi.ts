export class ApiFetchError extends Error {
  status: number;

  constructor(path: string, status: number, message?: string) {
    super(message ?? `API ${path} failed: ${status}`);
    this.name = 'ApiFetchError';
    this.status = status;
  }
}

export type ApiFetchParseAs = 'json' | 'text' | 'response';

export interface ApiFetchOptions extends RequestInit {
  parseAs?: ApiFetchParseAs;
}

export async function apiFetch<T>(path: string, projectId?: string, options?: ApiFetchOptions): Promise<T> {
  // If projectId is provided, rewrite /api/... -> /api/projects/{projectId}/...
  let resolvedPath = path;
  if (projectId && path.startsWith('/api/')) {
    resolvedPath = `/api/projects/${projectId}/${path.slice('/api/'.length)}`;
  }

  const headers = new Headers(options?.headers);
  if (options?.body !== undefined && options.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let signal = options?.signal;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const requestInit: RequestInit = {
    ...options,
    headers,
    signal,
  };

  if (!signal) {
    const controller = new AbortController();
    signal = controller.signal;
    timeoutId = setTimeout(() => controller.abort(), 15_000);
    requestInit.signal = signal;
  }

  try {
    const response = await fetch(resolvedPath, requestInit);
    if (!response.ok) {
      const rawError = await response.text();
      let detail = '';

      if (rawError.trim()) {
        try {
          const parsed = JSON.parse(rawError) as Record<string, unknown>;
          if (typeof parsed.error === 'string') {
            detail = parsed.error;
          } else {
            detail = rawError.trim();
          }
        } catch {
          detail = rawError.trim();
        }
      }

      const message = detail
        ? `${detail} (HTTP ${response.status})`
        : `API ${resolvedPath} failed: ${response.status}`;
      throw new ApiFetchError(resolvedPath, response.status, message);
    }

    switch (options?.parseAs ?? 'json') {
      case 'response':
        return response as T;
      case 'text':
        return await response.text() as T;
      case 'json':
      default:
        return await response.json();
    }
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}
