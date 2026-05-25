function constantTimeEqual(actual: Uint8Array, expected: Uint8Array): boolean {
  const maxLength = Math.max(actual.byteLength, expected.byteLength);
  let diff = actual.byteLength ^ expected.byteLength;

  for (let index = 0; index < maxLength; index += 1) {
    diff |= (actual[index] ?? 0) ^ (expected[index] ?? 0);
  }

  return diff === 0;
}

export async function hasValidBearerToken(
  request: Request,
  expected: string,
): Promise<boolean> {
  const header = request.headers.get("authorization");
  const actual = header?.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";
  const encoder = new TextEncoder();

  return constantTimeEqual(encoder.encode(actual), encoder.encode(expected));
}
