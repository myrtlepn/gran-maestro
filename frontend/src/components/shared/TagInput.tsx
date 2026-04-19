import { useState, type KeyboardEvent, useRef, useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { X } from 'lucide-react';

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
}

export function TagInput({ tags, onChange }: TagInputProps) {
  const [inputValue, setInputValue] = useState('');
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editValue, setEditValue] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingIndex !== null && editInputRef.current) {
      editInputRef.current.focus();
    }
  }, [editingIndex]);

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      const trimmed = inputValue.trim();
      if (trimmed && !tags.includes(trimmed)) {
        onChange([...tags, trimmed]);
      }
      setInputValue('');
    }
  }

  function handleRemove(index: number) {
    onChange(tags.filter((_, i) => i !== index));
  }

  function handleEditStart(index: number, tag: string) {
    setEditingIndex(index);
    setEditValue(tag);
  }

  function handleEditSave() {
    if (editingIndex === null) return;
    const trimmed = editValue.trim();
    if (!trimmed) {
      handleRemove(editingIndex);
    } else {
      const newTags = [...tags];
      if (!tags.includes(trimmed) || tags[editingIndex] === trimmed) {
        newTags[editingIndex] = trimmed;
        onChange(newTags);
      } else {
        onChange(tags.filter((_, i) => i !== editingIndex));
      }
    }
    setEditingIndex(null);
    setEditValue('');
  }

  function handleEditKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleEditSave();
    } else if (e.key === 'Escape') {
      setEditingIndex(null);
      setEditValue('');
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 min-w-0">
      {tags.map((tag, i) => (
        editingIndex === i ? (
          <Input
            key={`edit-${i}`}
            ref={editInputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleEditSave}
            onKeyDown={handleEditKeyDown}
            className="h-7 w-[120px] text-xs font-mono px-2"
          />
        ) : (
          <Badge 
            key={`${tag}-${i}`} 
            variant="secondary" 
            className="gap-1 shrink-0 cursor-pointer"
            onClick={() => handleEditStart(i, tag)}
            title="클릭하여 수정"
          >
            <span className="font-mono text-xs">{tag}</span>
            <button
              type="button"
              className="ml-0.5 rounded-full hover:bg-muted-foreground/20 p-0.5"
              onClick={(e) => {
                e.stopPropagation();
                handleRemove(i);
              }}
              aria-label={`Remove ${tag}`}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        )
      ))}
      <Input
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Add..."
        className="h-7 min-w-[80px] w-auto flex-1 text-xs font-mono"
      />
    </div>
  );
}
