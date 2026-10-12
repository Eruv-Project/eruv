// expo-location for tests: permission denied, so screens render without a position.
export const Accuracy = { High: 4, Balanced: 3 };
export const requestForegroundPermissionsAsync = jest.fn(async () => ({ status: 'denied' }));
export const watchPositionAsync = jest.fn(async () => ({ remove: jest.fn() }));
