import re

with open('frontend/src/views/AgileView.tsx', 'r') as f:
    content = f.read()

# Find the start of the TabsContent objective
start_marker = '<TabsContent value="objective" className="mt-0 outline-none">'
start_idx = content.find(start_marker)

if start_idx == -1:
    print("Could not find start marker")
    exit(1)

# Find the end of the xl:col-span-2 div
# We know the next thing is <div className="xl:col-span-1 h-[600px] xl:h-[calc(100vh-250px)] sticky top-0">
end_marker = '<div className="xl:col-span-1 h-[600px] xl:h-[calc(100vh-250px)] sticky top-0">'
end_idx = content.find(end_marker, start_idx)

if end_idx == -1:
    print("Could not find end marker")
    exit(1)

new_content = """<TabsContent value="objective" className="mt-0 outline-none">
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 h-full items-start">
                      <div className="xl:col-span-2 h-[600px] xl:h-[calc(100vh-250px)]">
                        <Card className="h-full flex flex-col shadow-sm">
                          <CardHeader className="pb-3 flex flex-row items-center justify-between border-b shrink-0">
                            <div>
                              <CardTitle className="text-base flex items-center gap-2">
                                <FileText className="h-4 w-4" /> Objective
                                <span className="text-xs text-muted-foreground font-normal">세션 전체 목표</span>
                              </CardTitle>
                              {selectedObjectiveFile === 'objective.md' && (
                                <CardDescription>
                                  세션의 목표와 요구사항
                                </CardDescription>
                              )}
                            </div>
                            {selectedObjectiveFile === 'objective.md' && objectiveContent !== null && (
                              <div className="inline-flex items-center rounded-md border border-input p-0.5 bg-muted/20">
                                <button
                                  type="button"
                                  onClick={() => handleObjectiveModeChange('preview')}
                                  className={`inline-flex h-8 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors ${
                                    !isObjectiveEditMode
                                      ? 'bg-background shadow-sm'
                                      : 'text-muted-foreground hover:bg-accent/40'
                                  }`}
                                >
                                  Preview
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleObjectiveModeChange('edit')}
                                  className={`inline-flex h-8 items-center justify-center rounded-sm px-3 text-sm font-medium transition-colors ${
                                    isObjectiveEditMode
                                      ? 'bg-background shadow-sm'
                                      : 'text-muted-foreground hover:bg-accent/40'
                                  }`}
                                >
                                  Edit
                                </button>
                              </div>
                            )}
                          </CardHeader>
                          
                          <div className="flex flex-1 min-h-0 overflow-hidden relative">
                            {/* Left Tree */}
                            {isObjectiveTreeCollapsed ? (
                              <div className="w-11 border-r bg-muted/10 shrink-0 flex flex-col items-center pt-3">
                                <button
                                  type="button"
                                  onClick={() => setIsObjectiveTreeCollapsed(false)}
                                  className="h-7 w-7 rounded-md border bg-background hover:bg-accent/40 text-muted-foreground flex items-center justify-center"
                                  aria-label="트리 펼치기"
                                  title="트리 펼치기"
                                >
                                  <ChevronRight className="h-4 w-4" />
                                </button>
                              </div>
                            ) : (
                              <div
                                ref={objectiveTreeRef}
                                style={{ width: objectiveTreeWidth }}
                                className="border-r flex flex-col min-h-0 shrink-0 bg-muted/5 relative"
                              >
                                <div className="p-3 border-b flex items-center justify-between gap-2 shrink-0">
                                  <span className="text-sm font-semibold flex items-center gap-2">
                                    <ListChecks className="h-4 w-4" />
                                    문서 목차
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => setIsObjectiveTreeCollapsed(true)}
                                    className="h-7 w-7 rounded-md border bg-background hover:bg-accent/40 text-muted-foreground flex items-center justify-center shrink-0"
                                    aria-label="트리 접기"
                                    title="트리 접기"
                                  >
                                    <ChevronLeft className="h-4 w-4" />
                                  </button>
                                </div>
                                <ScrollArea className="flex-1 min-h-0">
                                  <div className="p-2 space-y-1">
                                    {objectiveFiles.map((file) => {
                                      const isRoot = file === 'objective.md';
                                      return (
                                        <button
                                          key={file}
                                          type="button"
                                          onClick={() => setSelectedObjectiveFile(file)}
                                          className={`w-full text-left px-3 py-2 text-sm rounded-md transition-colors flex items-center gap-2 ${
                                            selectedObjectiveFile === file
                                              ? 'bg-primary/10 text-primary font-medium'
                                              : 'hover:bg-accent/50 text-muted-foreground'
                                          }`}
                                        >
                                          <FileText className="h-4 w-4 shrink-0" />
                                          <span className="truncate">{isRoot ? file : file.replace('details/', '')}</span>
                                        </button>
                                      );
                                    })}
                                  </div>
                                </ScrollArea>
                              </div>
                            )}

                            {!isObjectiveTreeCollapsed && (
                              <ResizableHandle isResizing={isObjectiveTreeResizing} onMouseDown={startObjectiveTreeResizing} />
                            )}

                            {/* Main Content */}
                            <div className="flex-1 min-w-0 overflow-auto bg-background p-4 relative flex flex-col">
                              {statusMessage && (
                                <div className={`mb-4 px-3 py-2 text-sm rounded-md shrink-0 ${
                                  statusMessage.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
                                }`}>
                                  {statusMessage.text}
                                </div>
                              )}
                              
                              {selectedObjectiveFile !== 'objective.md' ? (
                                <div className="flex-1 min-h-0 flex flex-col">
                                  {objectiveDetailLoading ? (
                                    <Skeleton className="h-40 w-full" />
                                  ) : objectiveDetailError ? (
                                    <div className="text-sm text-red-600 p-3 bg-red-50 rounded-md">
                                      {objectiveDetailError}
                                    </div>
                                  ) : objectiveDetailContent !== null ? (
                                    <div className="rounded-md border p-4 bg-background overflow-auto flex-1">
                                      <MarkdownRenderer content={objectiveDetailContent} />
                                    </div>
                                  ) : (
                                    <div className="text-sm text-muted-foreground py-8 text-center border rounded-md bg-muted/10">
                                      내용이 없습니다
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div className="flex-1 min-h-0 flex flex-col">
                                  {objectiveLoading ? (
                                    <Skeleton className="h-40 w-full" />
                                  ) : objectiveError ? (
                                    <div className="text-sm text-red-600 p-3 bg-red-50 rounded-md">
                                      {objectiveError}
                                    </div>
                                  ) : isObjectiveEditMode ? (
                                    <div className="space-y-4 overflow-auto flex-1">
                                      <MilkdownEditor
                                        defaultValue={objectiveEditValue}
                                        onChange={setObjectiveEditValue}
                                        className="min-h-[300px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring prose prose-sm max-w-none"
                                      />
                                      <div className="flex gap-2">
                                        <button
                                          type="button"
                                          onClick={handleSaveObjective}
                                          className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-4 py-2"
                                        >
                                          Save
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => handleObjectiveModeChange('preview')}
                                          className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors border border-input bg-background hover:bg-accent hover:text-accent-foreground h-9 px-4 py-2"
                                        >
                                          Cancel
                                        </button>
                                      </div>
                                    </div>
                                  ) : objectiveContent !== null ? (
                                    <div className="overflow-auto flex-1 pb-4">
                                      <div className="rounded-md border p-4 bg-background">
                                        <MarkdownRenderer content={objectiveContent} />
                                      </div>
                                      {renderDodStatus(objectiveDodItems)}
                                      {renderObjectiveSections(objectiveSections)}
                                    </div>
                                  ) : (
                                    <div className="text-sm text-muted-foreground py-8 text-center border rounded-md bg-muted/10">
                                      objective.md가 없습니다
                                    </div>
                                  )}
                                </div>
                              )}
                              
                              {/* Prev/Next Navigation */}
                              {objectiveFiles.length > 0 && (
                                <div className="mt-4 pt-4 border-t flex items-center justify-between shrink-0">
                                  {(() => {
                                    const currentIndex = objectiveFiles.indexOf(selectedObjectiveFile);
                                    const prevFile = currentIndex > 0 ? objectiveFiles[currentIndex - 1] : null;
                                    const nextFile = currentIndex < objectiveFiles.length - 1 && currentIndex !== -1 ? objectiveFiles[currentIndex + 1] : null;
                                    
                                    return (
                                      <>
                                        <button
                                          type="button"
                                          onClick={() => prevFile && setSelectedObjectiveFile(prevFile)}
                                          disabled={!prevFile}
                                          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md hover:bg-accent hover:text-accent-foreground disabled:opacity-50 disabled:pointer-events-none"
                                        >
                                          <ChevronLeft className="h-4 w-4" />
                                          이전
                                        </button>
                                        <span className="text-xs text-muted-foreground">
                                          {currentIndex + 1} / {objectiveFiles.length}
                                        </span>
                                        <button
                                          type="button"
                                          onClick={() => nextFile && setSelectedObjectiveFile(nextFile)}
                                          disabled={!nextFile}
                                          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md hover:bg-accent hover:text-accent-foreground disabled:opacity-50 disabled:pointer-events-none"
                                        >
                                          다음
                                          <ChevronRight className="h-4 w-4" />
                                        </button>
                                      </>
                                    );
                                  })()}
                                </div>
                              )}
                            </div>
                          </div>
                        </Card>
                      </div>
                      """

final_content = content[:start_idx] + new_content + end_marker + content[end_idx + len(end_marker):]

with open('frontend/src/views/AgileView.tsx', 'w') as f:
    f.write(final_content)

print("Updated AgileView.tsx successfully")
