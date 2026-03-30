import { useEffect, useRef } from 'react';
import { defaultValueCtx, Editor, rootCtx } from '@milkdown/core';
import { listener, listenerCtx } from '@milkdown/plugin-listener';
import { commonmark } from '@milkdown/preset-commonmark';
import { useEditor } from '@milkdown/react';
import { nord } from '@milkdown/theme-nord';

export interface MilkdownEditorAdapterOptions {
  initialMarkdown: string;
  onChange: (markdown: string) => void;
}

export function useMilkdownEditorAdapter({ initialMarkdown, onChange }: MilkdownEditorAdapterOptions) {
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  return useEditor(
    (root) =>
      Editor.make()
        .config((ctx) => {
          ctx.set(rootCtx, root);
          ctx.set(defaultValueCtx, initialMarkdown);
          ctx.get(listenerCtx).markdownUpdated((_, markdown) => {
            onChangeRef.current(markdown);
          });
        })
        .config(nord)
        .use(commonmark)
        .use(listener),
    [initialMarkdown],
  );
}
