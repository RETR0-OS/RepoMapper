export function validateProfileLabel(value: string): string | undefined {
  const clean = value.trim();
  if (!clean) return "Enter a profile label.";
  if (clean.length > 80 || /[\u0000-\u001f\u007f]/.test(clean)) return "Use at most 80 printable characters.";
  return undefined;
}

export function validateApiKey(value: string): string | undefined {
  const clean = value.trim();
  if (clean.length < 8) return "The API key must contain at least 8 characters.";
  if (clean.length > 8_192 || /[\u0000-\u001f\u007f]/.test(clean)) return "The API key contains unsupported characters.";
  return undefined;
}

export function validateDatabase(value: string): string | undefined {
  const clean = value.trim();
  if (!clean) return "Enter the HydraDB database name.";
  if (clean.length > 512 || /[\u0000-\u001f\u007f]/.test(clean)) return "The database name contains unsupported characters.";
  return undefined;
}
