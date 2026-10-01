import { api, REQUEST_TIMEOUT_MS } from '../src/api/client';
import { installFakeServer } from '../test-utils/server';

afterEach(() => jest.useRealTimers());

it('abandons a request with no answer after the timeout and surfaces a network error', async () => {
  jest.useFakeTimers();
  let signal: AbortSignal | undefined;
  (globalThis as any).fetch = jest.fn((_url: string, init: { signal?: AbortSignal }) => {
    signal = init.signal;
    return new Promise(() => undefined); // a hung connection
  });

  const request = api.cities();
  const outcome = request.then(
    () => 'resolved',
    (err) => err,
  );
  await jest.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
  expect(signal?.aborted).toBe(false);
  await jest.advanceTimersByTimeAsync(1);

  const err = await outcome;
  expect(err).toBeInstanceOf(TypeError);
  expect(signal?.aborted).toBe(true);
});

it('clears the timeout once the server answers', async () => {
  jest.useFakeTimers();
  const server = installFakeServer();
  server.on('GET', '/api/cities', { status: 200, body: [] });
  await expect(api.cities()).resolves.toEqual([]);
  expect(jest.getTimerCount()).toBe(0);
});
