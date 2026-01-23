/**
 * Error Handling Utilities
 *
 * Type-safe utilities for extracting error messages from unknown error types.
 */

/**
 * Extract error message from an unknown error type.
 *
 * @param error - The caught error (unknown type for TypeScript safety)
 * @param fallback - Fallback message if error message cannot be extracted
 * @returns The error message string
 *
 * @example
 * try {
 *   await someAsyncOperation();
 * } catch (err: unknown) {
 *   setError(getErrorMessage(err, 'Operation failed'));
 * }
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  // Check for standard Error objects
  if (error instanceof Error) {
    return error.message || fallback;
  }

  // Check for string errors (thrown directly)
  if (typeof error === 'string') {
    return error;
  }

  // Check for Axios-style errors with response.data.detail
  if (isAxiosError(error) && error.response?.data?.detail) {
    return error.response.data.detail;
  }

  // Check for objects with a message property
  if (isErrorWithMessage(error)) {
    return error.message;
  }

  return fallback;
}

/**
 * Type guard for objects with a message property.
 */
function isErrorWithMessage(error: unknown): error is { message: string } {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    typeof (error as { message: unknown }).message === 'string'
  );
}

/**
 * Type guard for Axios-like errors with response data.
 */
function isAxiosError(
  error: unknown
): error is { response?: { data?: { detail?: string } } } {
  return (
    typeof error === 'object' &&
    error !== null &&
    'response' in error
  );
}

/**
 * Safely log an error with context.
 *
 * @param context - Context string for the log (e.g., '[Redux]', '[API]')
 * @param error - The caught error
 */
export function logError(context: string, error: unknown): void {
  console.error(`${context}:`, error instanceof Error ? error : String(error));
}

/**
 * Detect request cancellation across common client implementations.
 */
export function isRequestCanceled(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }

  if (typeof error === 'object' && error !== null) {
    if ('code' in error) {
      const code = (error as { code?: string }).code;
      if (code === 'ERR_CANCELED' || code === 'ECONNABORTED') {
        return true;
      }
    }
    if ('name' in error) {
      const name = (error as { name?: string }).name;
      if (name === 'CanceledError') {
        return true;
      }
    }
  }

  return false;
}

/**
 * Best-effort extraction of error code from unknown errors.
 */
export function getErrorCode(error: unknown): string | undefined {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = (error as { code?: unknown }).code;
    return typeof code === 'string' ? code : undefined;
  }
  return undefined;
}
