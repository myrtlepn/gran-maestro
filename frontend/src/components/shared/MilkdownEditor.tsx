import { Milkdown, MilkdownProvider } from '@milkdown/react';
import { useMilkdownEditorAdapter } from '@/components/shared/useMilkdownEditorAdapter';

export interface MilkdownEditorProps {
  defaultValue: string;
  onChange: (markdown: string) => void;
  className?: string;
}

function EditorComponent({ defaultValue, onChange, className }: MilkdownEditorProps) {
  useMilkdownEditorAdapter({
    initialMarkdown: defaultValue,
    onChange,
  });

  return (
    <div className={`milkdown-wrapper ${className ?? ''}`}>
      <Milkdown />
    </div>
  );
}

export function MilkdownEditor(props: MilkdownEditorProps) {
  return (
    <MilkdownProvider>
      <EditorComponent {...props} />
    </MilkdownProvider>
  );
}
