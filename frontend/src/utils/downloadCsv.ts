/** Build a CSV from uniform row records and trigger a browser download. */
export const downloadCsv = (
  filename: string,
  headers: string[],
  rows: Array<Record<string, unknown>>,
): void => {
  const csv = [
    headers.join(','),
    ...rows.map((row) => headers.map((h) => JSON.stringify(row[h] ?? '')).join(',')),
  ].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};
