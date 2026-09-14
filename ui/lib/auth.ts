import { create as createPasskey, get as getPasskey, isSupported } from 'react-native-passkeys';
import { api, AccessStatus, AuthStatus } from './api';
import { saveSessionToken } from './storage';

function asCredential(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object') throw new Error('No passkey credential was returned');
  return value as Record<string, unknown>;
}

async function persistSession(token?: string) {
  if (token) await saveSessionToken(token);
}

export async function enrollFirstPasskey(code: string): Promise<AuthStatus> {
  if (!isSupported()) throw new Error('Passkeys are not supported on this device/browser');
  const ceremony = await api.bootstrapOptions(code.trim().toUpperCase());
  const credential = await createPasskey(ceremony.options as never);
  const session = await api.bootstrapVerify(
    code.trim().toUpperCase(),
    ceremony.challenge_id,
    asCredential(credential),
  );
  await persistSession(session.token);
  return api.authStatus();
}

export async function signInWithPasskey(): Promise<AuthStatus> {
  if (!isSupported()) throw new Error('Passkeys are not supported on this device/browser');
  const ceremony = await api.loginOptions();
  const credential = await getPasskey(ceremony.options as never);
  const session = await api.loginVerify(ceremony.challenge_id, asCredential(credential));
  await persistSession(session.token);
  return api.authStatus();
}

export async function addPasskey(): Promise<void> {
  if (!isSupported()) throw new Error('Passkeys are not supported on this device/browser');
  const ceremony = await api.registerOptions();
  const credential = await createPasskey(ceremony.options as never);
  await api.registerVerify(ceremony.challenge_id, asCredential(credential));
}

export async function approveAccessChange(approvalId: string): Promise<AccessStatus> {
  if (!isSupported()) throw new Error('Passkeys are not supported on this device/browser');
  const ceremony = await api.accessApprovalOptions(approvalId);
  const credential = await getPasskey(ceremony.options as never);
  const result = await api.verifyAccessApproval(
    approvalId,
    ceremony.challenge_id,
    asCredential(credential),
  );
  return result.status;
}

export async function signOut(): Promise<void> {
  try {
    await api.logout();
  } finally {
    await saveSessionToken('');
  }
}
