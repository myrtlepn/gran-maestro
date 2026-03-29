import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BookOpen, ExternalLink, Search } from 'lucide-react';
import { useAppContext } from '@/context/AppContext';
import { apiFetch } from '@/hooks/useApi';
import { useResizableSidebar } from '@/hooks/useResizableSidebar';
import { ResizableHandle } from '@/components/shared/ResizableHandle';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { SessionCard } from '@/components/shared/SessionCard';
import { RefreshButton } from '@/components/shared/RefreshButton';
import { EmptyState } from '@/components/shared/EmptyState';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer';

interface ReferenceItem {
  id: string;
  topic: string;
  url: string;
  summary: string;
  searched_at: string;
  freshness: 'fresh' | 'stale' | 'expired' | string;
  content_path?: string;
  content?: string;
}

export function ReferenceView() {
  const { projectId } = useAppContext();
  const { refId } = useParams();
  const navigate = useNavigate();

  const [references, setReferences] = useState<ReferenceItem[]>([]);
  const [referenceDetail, setReferenceDetail] = useState<ReferenceItem | null>(null);

  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const [searchValue, setSearchValue] = useState('');

  const { sidebarWidth, isResizing, startResizing, sidebarRef } = useResizableSidebar({
    defaultWidth: 320,
    minWidth: 260,
    maxWidth: 620,
    storageKey: 'references-sidebar-width',
  });

  const sortedReferences = useMemo(() => {
    return [...references].sort((a, b) =>
      (b.searched_at ?? '').localeCompare(a.searched_at ?? ''),
    );
  }, [references]);

  const selectedRefId = useMemo(() => {
    if (refId) return refId;
    return sortedReferences[0]?.id ?? null;
  }, [refId, sortedReferences]);

  const fetchReferences = useCallback(async (filters?: { query?: string }) => {
    const params = new URLSearchParams();
    const query = filters?.query?.trim();

    let url = '/api/references';
    if (query) {
      url = '/api/references/search';
      params.set('q', query);
    }
    
    const queryString = params.toString();
    if (queryString) url += `?${queryString}`;

    const data = await apiFetch<ReferenceItem[]>(url, projectId);
    setReferences(Array.isArray(data) ? data : []);
  }, [projectId]);

  const fetchReferenceDetail = useCallback(async (id: string) => {
    const detail = await apiFetch<ReferenceItem>(`/api/references/${id}`, projectId);
    setReferenceDetail(detail);
  }, [projectId]);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setReferences([]);
      return;
    }

    setLoading(true);
    fetchReferences()
      .catch((error: unknown) => {
        setStatusMessage(error instanceof Error ? error.message : 'Reference 목록을 불러오지 못했습니다');
      })
      .finally(() => setLoading(false));
  }, [fetchReferences, projectId]);

  useEffect(() => {
    const query = searchValue.trim();
    if (!projectId) return;

    let cancelled = false;
    const timer = setTimeout(() => {
      fetchReferences({ query }).catch(() => {
        if (!cancelled) setReferences([]);
      });
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [fetchReferences, projectId, searchValue]);

  useEffect(() => {
    if (!selectedRefId || !projectId) {
      setReferenceDetail(null);
      return;
    }

    setIsDetailLoading(true);
    fetchReferenceDetail(selectedRefId)
      .catch(() => {
        setReferenceDetail(null);
      })
      .finally(() => setIsDetailLoading(false));
  }, [fetchReferenceDetail, projectId, selectedRefId]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setStatusMessage(null);
    try {
      await fetchReferences({ query: searchValue.trim() });
      if (selectedRefId) {
        await fetchReferenceDetail(selectedRefId);
      }
    } catch (error: unknown) {
      setStatusMessage(error instanceof Error ? error.message : '새로고침에 실패했습니다');
    } finally {
      setIsRefreshing(false);
    }
  };

  const displayReferences = sortedReferences;
  const hasActiveFilters = Boolean(searchValue.trim());

  if (!projectId) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        프로젝트를 선택하세요
      </div>
    );
  }

  if (loading) {
    return (
      <div className="grid grid-cols-12 gap-6 h-full p-6">
        <div className="col-span-4 space-y-4">
          {[1, 2, 3].map((index) => <Skeleton key={index} className="h-24 w-full" />)}
        </div>
        <div className="col-span-8">
          <Skeleton className="h-full w-full" />
        </div>
      </div>
    );
  }

  const getFreshnessColor = (freshness: string) => {
    switch (freshness) {
      case 'fresh': return 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800';
      case 'stale': return 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800';
      case 'expired': return 'bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800';
      default: return '';
    }
  };

  return (
    <div className="flex h-full overflow-hidden">
      <div ref={sidebarRef} style={{ width: sidebarWidth }} className="border-r flex flex-col min-h-0 shrink-0">
        <div className="p-4 border-b bg-muted/30 flex justify-between items-center gap-2">
          <h2 className="font-semibold">References ({displayReferences.length})</h2>
          <div className="flex items-center gap-2">
            <RefreshButton onClick={handleRefresh} isRefreshing={isRefreshing} />
          </div>
        </div>

        <div className="p-3 border-b space-y-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              placeholder="Search references..."
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>

        {statusMessage && (
          <div className="px-3 py-2 border-b text-xs text-destructive bg-destructive/5">
            {statusMessage}
          </div>
        )}

        <ScrollArea className="flex-1">
          <div className="p-3 space-y-1.5">
            {displayReferences.map((ref) => (
              <SessionCard
                key={ref.id}
                id={ref.id}
                title={ref.topic || ref.id}
                status={ref.freshness === 'fresh' ? 'active' : ref.freshness === 'expired' ? 'closed' : 'pending'}
                createdAt={ref.searched_at}
                icon={<BookOpen className="h-3.5 w-3.5 text-muted-foreground" />}
                isSelected={selectedRefId === ref.id}
                onClick={() => navigate(`/memory/references/${ref.id}`)}
              />
            ))}

            {displayReferences.length === 0 && (
              <div className="pt-8">
                <EmptyState
                  icon={<BookOpen className="h-8 w-8" />}
                  title={hasActiveFilters ? '검색 결과 없음' : 'Reference 없음'}
                  description={hasActiveFilters ? '조건에 맞는 결과가 없습니다.' : '수집된 레퍼런스가 없습니다.'}
                />
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      <ResizableHandle isResizing={isResizing} onMouseDown={startResizing} />

      <div className="flex-1 flex flex-col bg-card min-h-0 overflow-hidden">
        {!selectedRefId ? (
          <EmptyState
            icon={<BookOpen className="h-8 w-8" />}
            title="Reference 없음"
            description="목록에서 Reference를 선택하세요."
          />
        ) : isDetailLoading ? (
          <div className="p-6 h-full">
            <Skeleton className="h-full w-full" />
          </div>
        ) : referenceDetail ? (
          <>
            <div className="p-4 border-b flex justify-between items-center bg-muted/10">
              <div>
                <h2 className="font-bold text-lg">{referenceDetail.topic || referenceDetail.id}</h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-muted-foreground font-mono">
                    {referenceDetail.id}
                  </span>
                  {referenceDetail.searched_at && (
                    <span className="text-xs text-muted-foreground">
                      · 검색: {referenceDetail.searched_at.slice(0, 10)}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {referenceDetail.freshness && (
                  <Badge variant="outline" className={getFreshnessColor(referenceDetail.freshness)}>
                    {referenceDetail.freshness.toUpperCase()}
                  </Badge>
                )}
              </div>
            </div>

            <ScrollArea className="flex-1">
              <div className="p-6">
                <Tabs key={selectedRefId} defaultValue="metadata" className="w-full">
                  <TabsList className="mb-4">
                    <TabsTrigger value="metadata">Metadata</TabsTrigger>
                    <TabsTrigger value="content">Content</TabsTrigger>
                  </TabsList>

                  <TabsContent value="metadata">
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base">Metadata</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {referenceDetail.url && (
                          <div className="flex flex-col gap-1">
                            <span className="text-xs font-semibold text-muted-foreground">URL</span>
                            <a 
                              href={referenceDetail.url} 
                              target="_blank" 
                              rel="noreferrer" 
                              className="text-sm text-blue-500 hover:underline flex items-center gap-1 w-fit break-all"
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                              {referenceDetail.url}
                            </a>
                          </div>
                        )}
                        {referenceDetail.summary && (
                          <div className="flex flex-col gap-1">
                            <span className="text-xs font-semibold text-muted-foreground">Summary</span>
                            <p className="text-sm">{referenceDetail.summary}</p>
                          </div>
                        )}
                        {referenceDetail.content_path && (
                          <div className="flex flex-col gap-1 mt-2">
                            <span className="text-xs font-semibold text-muted-foreground">Content Path</span>
                            <p className="text-xs font-mono bg-muted/50 p-1.5 rounded">{referenceDetail.content_path}</p>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </TabsContent>

                  <TabsContent value="content">
                    {referenceDetail.content ? (
                      <Card>
                        <CardHeader className="pb-3">
                          <CardTitle className="text-base">Content</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <MarkdownRenderer content={referenceDetail.content} className="px-1" />
                        </CardContent>
                      </Card>
                    ) : (
                      <div className="py-12">
                        <EmptyState
                          icon={<BookOpen className="h-8 w-8" />}
                          title="Content 없음"
                          description="저장된 본문(content)이 없습니다."
                        />
                      </div>
                    )}
                  </TabsContent>
                </Tabs>
              </div>
            </ScrollArea>
          </>
        ) : (
          <EmptyState
            icon={<BookOpen className="h-8 w-8" />}
            title="Reference를 찾을 수 없음"
            description="목록에서 다른 항목을 선택하세요."
          />
        )}
      </div>
    </div>
  );
}
