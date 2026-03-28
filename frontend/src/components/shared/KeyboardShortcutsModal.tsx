import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface KeyboardShortcutsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SHORTCUTS = [
  { category: 'Navigation', key: '`', action: 'Overview 뷰로 전환' },
  { category: 'Navigation', key: '0', action: 'Agile 뷰로 전환' },
  { category: 'Navigation', key: '1', action: 'Picks 뷰로 전환' },
  { category: 'Navigation', key: '2', action: 'Plans 뷰로 전환' },
  { category: 'Navigation', key: '3', action: 'Workflow 뷰로 전환' },
  { category: 'Navigation', key: '4', action: 'Ideation 뷰로 전환' },
  { category: 'Navigation', key: '5', action: 'Debug 뷰로 전환' },
  { category: 'Navigation', key: '6', action: 'Designs 뷰로 전환' },
  { category: 'Navigation', key: '7', action: 'Documents 뷰로 전환' },
  { category: 'Navigation', key: 'i', action: 'Memory 뷰로 전환' },
  { category: 'Navigation', key: '8', action: 'Settings 뷰로 전환' },
  { category: 'UI', key: 'T', action: '테마 토글 (Light ↔ Dark)' },
  { category: 'Help', key: '?', action: '단축키 도움말 열기/닫기' },
];

export function KeyboardShortcutsModal({ open, onOpenChange }: KeyboardShortcutsModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>키보드 단축키</DialogTitle>
          <DialogDescription>현재 화면에서 사용할 수 있는 단축키 목록입니다.</DialogDescription>
        </DialogHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="pb-2 pr-2 text-left font-semibold text-muted-foreground">카테고리</th>
                <th className="pb-2 pr-2 text-left font-semibold text-muted-foreground">키</th>
                <th className="pb-2 text-left font-semibold text-muted-foreground">동작</th>
              </tr>
            </thead>
            <tbody>
              {SHORTCUTS.map((item) => (
                <tr key={`${item.category}-${item.key}`} className="border-b last:border-b-0">
                  <td className="py-2 pr-2 text-muted-foreground">{item.category}</td>
                  <td className="py-2 pr-2">
                    <span className="inline-flex min-w-6 rounded border px-2 py-0.5 text-xs font-mono">
                      {item.key}
                    </span>
                  </td>
                  <td className="py-2">{item.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  );
}
