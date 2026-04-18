import type { MouseEvent, RefObject } from 'react';
import { ChevronLeft, ChevronRight, FileText, ListChecks } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';
import { MilkdownEditor } from '@/components/shared/MilkdownEditor';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { ObjectiveCommentsPanel } from '@/views/ObjectiveCommentsPanel';
import type { ObjectiveParsedSection } from './types';

interface ObjectiveWorkspaceProps {
  selectedSessionId: string | null;
  objectiveLoading: boolean;
  objectiveError: string | null;
  objectiveContent: string | null;
  objectiveSections: ObjectiveParsedSection[];
  isObjectiveEditMode: boolean;
  objectiveEditValue: string;
  statusMessage: { type: 'success' | 'error'; text: string } | null;
  selectedObjectiveFile: string;
  objectiveFiles: string[];
  objectiveDetailContent: string | null;
  objectiveDetailLoading: boolean;
  objectiveDetailError: string | null;
  isObjectiveTreeCollapsed: boolean;
  setIsObjectiveTreeCollapsed: (value: boolean) => void;
  objectiveTreeWidth: number;
  objectiveTreeRef: RefObject<HTMLDivElement | null>;
  isObjectiveTreeResizing: boolean;
  startObjectiveTreeResizing: (event: MouseEvent) => void;
  isObjectiveCommentsCollapsed: boolean;
  setIsObjectiveCommentsCollapsed: (value: boolean) => void;
  setSelectedObjectiveFile: (filename: string) => void;
  setObjectiveEditValue: (value: string) => void;
  onObjectiveModeChange: (mode: 'preview' | 'edit') => void;
  onSaveObjective: () => void;
  rewriteMarkdown: (content: string) => string;
  onObjectiveMarkdownLinkClick: (e: MouseEvent<HTMLAnchorElement>, href: string) => void;
}

export function ObjectiveWorkspace(props: ObjectiveWorkspaceProps) {
  const filesForNav = props.objectiveFiles.length > 0 ? props.objectiveFiles : ['objective.md'];
  const currentIndex = filesForNav.indexOf(props.selectedObjectiveFile);
  const prevFile = currentIndex > 0 ? filesForNav[currentIndex - 1] : null;
  const nextFile = currentIndex >= 0 && currentIndex < filesForNav.length - 1 ? filesForNav[currentIndex + 1] : null;

  return (
    <div className={`grid grid-cols-1 gap-4 ${props.isObjectiveCommentsCollapsed ? 'xl:flex xl:flex-row' : 'xl:grid-cols-3'}`}>
      <div className={`${props.isObjectiveCommentsCollapsed ? 'flex-1 min-w-0' : 'xl:col-span-2'} h-[600px] xl:h-[calc(100vh-240px)]`}>
        <Card className="flex h-full flex-col shadow-sm">
          <CardHeader className="flex shrink-0 flex-row items-center justify-between border-b pb-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4" /> Objective
              </CardTitle>
              {props.selectedObjectiveFile === 'objective.md' ? <CardDescription>세션 목표와 요구사항</CardDescription> : null}
            </div>

            {props.selectedObjectiveFile === 'objective.md' && props.objectiveContent !== null ? (
              <div className="inline-flex items-center rounded-md border border-input bg-muted/20 p-0.5">
                {(['preview', 'edit'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => props.onObjectiveModeChange(mode)}
                    className={`inline-flex h-8 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors ${
                      (mode === 'edit') === props.isObjectiveEditMode ? 'bg-background shadow-sm' : 'text-muted-foreground hover:bg-accent/40'
                    }`}
                  >
                    {mode === 'preview' ? 'Preview' : 'Edit'}
                  </button>
                ))}
              </div>
            ) : null}
          </CardHeader>

          <div className="relative flex min-h-0 flex-1 overflow-hidden">
            {props.isObjectiveTreeCollapsed ? (
              <div className="flex w-11 shrink-0 flex-col items-center border-r bg-muted/10 pt-3">
                <button
                  type="button"
                  onClick={() => props.setIsObjectiveTreeCollapsed(false)}
                  className="flex h-7 w-7 items-center justify-center rounded-md border bg-background text-muted-foreground hover:bg-accent/40"
                  aria-label="트리 펼치기"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div ref={props.objectiveTreeRef} style={{ width: props.objectiveTreeWidth }} className="relative flex min-h-0 shrink-0 flex-col border-r bg-muted/5">
                <div className="flex items-center justify-between gap-2 border-b p-3">
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <ListChecks className="h-4 w-4" /> 문서 목차
                  </span>
                  <button
                    type="button"
                    onClick={() => props.setIsObjectiveTreeCollapsed(true)}
                    className="flex h-7 w-7 items-center justify-center rounded-md border bg-background text-muted-foreground hover:bg-accent/40"
                    aria-label="트리 접기"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                </div>
                <ScrollArea className="min-h-0 flex-1">
                  <div className="space-y-1 p-2">
                    {filesForNav.map((file) => (
                      <button
                        key={file}
                        type="button"
                        onClick={() => props.setSelectedObjectiveFile(file)}
                        className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                          props.selectedObjectiveFile === file ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent/50'
                        }`}
                      >
                        <FileText className="h-4 w-4 shrink-0" />
                        <span className="truncate">{file === 'objective.md' ? file : file.replace('details/', '')}</span>
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}

            {!props.isObjectiveTreeCollapsed ? (
              <ResizableHandle isResizing={props.isObjectiveTreeResizing} onMouseDown={props.startObjectiveTreeResizing} />
            ) : null}

            <div className="relative flex min-w-0 flex-1 flex-col overflow-auto bg-background p-4">
              {props.statusMessage ? (
                <div className={`mb-4 rounded-md border px-3 py-2 text-sm ${
                  props.statusMessage.type === 'success' ? 'border-green-200 bg-green-50 text-green-700' : 'border-red-200 bg-red-50 text-red-700'
                }`}>
                  {props.statusMessage.text}
                </div>
              ) : null}

              {props.selectedObjectiveFile !== 'objective.md' ? (
                props.objectiveDetailLoading ? <Skeleton className="h-40 w-full" /> : props.objectiveDetailError ? (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{props.objectiveDetailError}</div>
                ) : props.objectiveDetailContent ? (
                  <div className="flex-1 rounded-md border bg-background p-4">
                    <MarkdownRenderer content={props.rewriteMarkdown(props.objectiveDetailContent)} onLinkClick={props.onObjectiveMarkdownLinkClick} />
                  </div>
                ) : (
                  <div className="rounded-md border bg-muted/10 py-8 text-center text-sm text-muted-foreground">내용이 없습니다.</div>
                )
              ) : props.objectiveLoading ? (
                <Skeleton className="h-40 w-full" />
              ) : props.objectiveError ? (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{props.objectiveError}</div>
              ) : props.isObjectiveEditMode ? (
                <div className="flex-1 space-y-4 overflow-auto">
                  <MilkdownEditor
                    defaultValue={props.objectiveEditValue}
                    onChange={props.setObjectiveEditValue}
                    className="min-h-[300px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm"
                  />
                  <div className="flex gap-2">
                    <button type="button" onClick={props.onSaveObjective} className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                      Save
                    </button>
                    <button type="button" onClick={() => props.onObjectiveModeChange('preview')} className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 text-sm font-medium hover:bg-accent">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : props.objectiveContent ? (
                <div className="flex-1 overflow-auto pb-4">
                  <div className="rounded-md border bg-background p-4">
                    <MarkdownRenderer content={props.rewriteMarkdown(props.objectiveContent)} onLinkClick={props.onObjectiveMarkdownLinkClick} />
                  </div>
                  {props.objectiveSections.length > 0 ? (
                    <Card className="mt-4">
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base">Objective Sections</CardTitle>
                        <CardDescription>설계, 제약, 리스크 요약</CardDescription>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {props.objectiveSections.map((section, index) => (
                          <div key={`${section.key}-${index}`} className="rounded-md border bg-muted/5 p-3">
                            <h4 className="mb-2 text-sm font-semibold">{section.title}</h4>
                            <MarkdownRenderer content={props.rewriteMarkdown(section.content)} onLinkClick={props.onObjectiveMarkdownLinkClick} />
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-md border bg-muted/10 py-8 text-center text-sm text-muted-foreground">objective.md가 없습니다.</div>
              )}

              {props.objectiveContent || props.objectiveFiles.length > 0 ? (
                <div className="mt-4 flex shrink-0 items-center justify-between border-t pt-4">
                  <button type="button" onClick={() => prevFile && props.setSelectedObjectiveFile(prevFile)} disabled={!prevFile} className="inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:pointer-events-none disabled:opacity-50">
                    <ChevronLeft className="h-4 w-4" /> 이전
                  </button>
                  <span className="text-xs text-muted-foreground">{Math.max(currentIndex + 1, 1)} / {filesForNav.length}</span>
                  <button type="button" onClick={() => nextFile && props.setSelectedObjectiveFile(nextFile)} disabled={!nextFile} className="inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:pointer-events-none disabled:opacity-50">
                    다음 <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </Card>
      </div>

      {props.isObjectiveCommentsCollapsed ? (
        <div className="sticky top-0 flex h-[600px] w-11 shrink-0 items-start justify-center rounded-md border bg-muted/10 pt-3 xl:h-[calc(100vh-240px)]">
          <button type="button" onClick={() => props.setIsObjectiveCommentsCollapsed(false)} className="flex h-7 w-7 items-center justify-center rounded-md border bg-background text-muted-foreground hover:bg-accent/40" aria-label="코멘트 패널 펼치기">
            <ChevronLeft className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="h-[600px] xl:col-span-1 xl:h-[calc(100vh-240px)]">
          {props.selectedSessionId ? (
            <ObjectiveCommentsPanel agiId={props.selectedSessionId} onCollapse={() => props.setIsObjectiveCommentsCollapsed(true)} />
          ) : (
            <Card className="relative flex h-full items-center justify-center bg-muted/5 text-sm text-muted-foreground">
              <button type="button" onClick={() => props.setIsObjectiveCommentsCollapsed(true)} className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-md border bg-background text-muted-foreground hover:bg-accent/40" aria-label="코멘트 패널 접기">
                <ChevronRight className="h-4 w-4" />
              </button>
              세션을 선택하세요
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
