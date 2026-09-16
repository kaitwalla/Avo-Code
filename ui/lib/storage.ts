import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const SESSION_TOKEN_KEY = 'avo.sessionToken';
const ACTIVE_CONVERSATION_KEY = 'avo.activeConversationId';

export function apiBaseUrl(): string {
  if (Platform.OS === 'web') return '';
  return (process.env.EXPO_PUBLIC_AVO_API_URL || 'https://avo.penginlab.com').replace(/\/$/, '');
}

export async function loadSessionToken(): Promise<string> {
  if (Platform.OS === 'web') return '';
  return (await SecureStore.getItemAsync(SESSION_TOKEN_KEY)) ?? '';
}

export async function saveSessionToken(token: string): Promise<void> {
  if (Platform.OS === 'web') return;
  if (!token) {
    await SecureStore.deleteItemAsync(SESSION_TOKEN_KEY);
    return;
  }
  await SecureStore.setItemAsync(SESSION_TOKEN_KEY, token);
}

export async function loadActiveConversationId(): Promise<string> {
  if (Platform.OS === 'web') {
    if (typeof window === 'undefined') return '';
    return window.localStorage.getItem(ACTIVE_CONVERSATION_KEY) ?? '';
  }
  return (await SecureStore.getItemAsync(ACTIVE_CONVERSATION_KEY)) ?? '';
}

export async function saveActiveConversationId(conversationId: string): Promise<void> {
  if (Platform.OS === 'web') {
    if (typeof window === 'undefined') return;
    if (conversationId) window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, conversationId);
    else window.localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
    return;
  }
  if (!conversationId) {
    await SecureStore.deleteItemAsync(ACTIVE_CONVERSATION_KEY);
    return;
  }
  await SecureStore.setItemAsync(ACTIVE_CONVERSATION_KEY, conversationId);
}
