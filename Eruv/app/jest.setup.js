// The API base URL normally comes from app/.env at build time.
process.env.EXPO_PUBLIC_API_URL = 'https://api.test';

jest.mock('react-native-safe-area-context', () => require('react-native-safe-area-context/jest/mock').default);
