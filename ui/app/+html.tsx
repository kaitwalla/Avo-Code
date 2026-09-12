import { PropsWithChildren } from 'react';
import { ScrollViewStyleReset } from 'expo-router/html';

const globalCss = `
html, body, #root {
  width: 100%;
  height: 100%;
  min-height: 100%;
  margin: 0;
  padding: 0;
  background: #0b0c10;
}

body {
  min-height: 100dvh;
  overflow: hidden;
  overscroll-behavior: none;
}

#root {
  height: 100dvh;
  min-height: 100dvh;
  overflow: hidden;
}

* {
  box-sizing: border-box;
}
`;

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"
        />
        <meta name="theme-color" content="#0b0c10" />
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: globalCss }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
