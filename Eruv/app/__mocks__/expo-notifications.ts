// Controllable expo-notifications for tests.
type Status = 'granted' | 'denied' | 'undetermined';
const state = { status: 'undetermined' as Status, requestResult: 'denied' as Status, token: 'ExponentPushToken[test]' };
const responseListeners: Array<(r: unknown) => void> = [];

export const __state = state;
export const __emitResponse = (response: unknown) => responseListeners.forEach((l) => l(response));
export const __reset = () => {
  state.status = 'undetermined';
  state.requestResult = 'denied';
  state.token = 'ExponentPushToken[test]';
  responseListeners.length = 0;
};

export const AndroidImportance = { MAX: 5, HIGH: 4, DEFAULT: 3 };
export const getPermissionsAsync = jest.fn(async () => ({ status: state.status, granted: state.status === 'granted' }));
export const requestPermissionsAsync = jest.fn(async () => {
  state.status = state.requestResult;
  return { status: state.status, granted: state.status === 'granted' };
});
export const getExpoPushTokenAsync = jest.fn(async () => ({ type: 'expo', data: state.token }));
export const setNotificationHandler = jest.fn();
export const setNotificationChannelAsync = jest.fn(async () => null);
export const getLastNotificationResponseAsync = jest.fn(async () => null);
export const addNotificationResponseReceivedListener = jest.fn((listener: (r: unknown) => void) => {
  responseListeners.push(listener);
  return {
    remove: () => {
      const i = responseListeners.indexOf(listener);
      if (i >= 0) responseListeners.splice(i, 1);
    },
  };
});
export const clearLastNotificationResponseAsync = jest.fn(async () => undefined);
