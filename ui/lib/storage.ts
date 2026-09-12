import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const API_URL_KEY = 'avo.apiUrl';
const TOKEN_KEY = 'avo.token';

async function getValue(key: string): Promise<string | null> {
  if (Platform.OS === 'web') {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem(key);
  }
  return SecureStore.getItemAsync(key);
}

async function setValue(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    window.localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function loadConnection() {
  return {
    apiUrl: (await getValue(API_URL_KEY)) ?? 'https://avo.penginlab.com',
    token: (await getValue(TOKEN_KEY)) ?? '',
  };
}

export async function saveConnection(apiUrl: string, token: string) {
  await setValue(API_URL_KEY, apiUrl.replace(/\/$/, ''));
  await setValue(TOKEN_KEY, token);
}
