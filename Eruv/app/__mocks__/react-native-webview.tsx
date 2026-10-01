// WebView stand-in for tests: a plain View that records injected scripts.
import { forwardRef, useImperativeHandle } from 'react';
import { View } from 'react-native';

export const __injected: string[] = [];

export const WebView = forwardRef(function WebView(props: any, ref) {
  useImperativeHandle(ref, () => ({
    injectJavaScript: (script: string) => {
      __injected.push(script);
    },
    postMessage: () => undefined,
    reload: () => undefined,
  }));
  return <View testID="webview" {...props} />;
});

export default WebView;
