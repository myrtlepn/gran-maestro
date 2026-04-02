import { useCallback, useEffect, useState } from 'react';
import { useAppContext } from '@/context/AppContext';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { MessageSquare, Check, RotateCcw, ChevronRight } from 'lucide-react';

interface ObjectiveComment {
  id: string;
  author: string;
  body: string;
  createdAt: string;
  status: 'open' | 'resolved';
  tags: string[];
}

interface ObjectiveCommentsResponse {
  docPath: string;
  docRevision: string | null;
  updatedAt: string;
  comments: ObjectiveComment[];
}

export function ObjectiveCommentsPanel({ agiId, onCollapse }: { agiId: string, onCollapse?: () => void }) {
  const { projectId, lastSseEvent } = useAppContext();
  const [comments, setComments] = useState<ObjectiveComment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [newCommentBody, setNewCommentBody] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  const [filter, setFilter] = useState<'all' | 'open' | 'resolved'>('all');

  const fetchComments = useCallback(async () => {
    if (!projectId || !agiId) return;
    
    setLoading(true);
    try {
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/${agiId}/objective/comments`
        : `/api/agile/${agiId}/objective/comments`;

      const response = await fetch(resolvedPath);
      if (!response.ok) {
        if (response.status === 404) {
          setComments([]);
          return;
        }
        throw new Error(`Failed to load comments: ${response.status}`);
      }
      
      const data: ObjectiveCommentsResponse = await response.json();
      setComments(data.comments || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '코멘트를 불러오지 못했습니다');
    } finally {
      setLoading(false);
    }
  }, [projectId, agiId]);

  useEffect(() => {
    fetchComments();
  }, [fetchComments]);

  useEffect(() => {
    if (!lastSseEvent || !agiId) return;
    
    if (lastSseEvent.type === 'objective_comment_added') {
      const eventAgiId = lastSseEvent.data?.agiId || lastSseEvent.sessionId;
      if (eventAgiId === agiId) {
        fetchComments();
      }
    }
  }, [lastSseEvent, agiId, fetchComments]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCommentBody.trim() || !projectId || !agiId) return;
    
    setIsSubmitting(true);
    try {
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/${agiId}/objective/comments`
        : `/api/agile/${agiId}/objective/comments`;

      const response = await fetch(resolvedPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: newCommentBody }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to post comment: ${response.status}`);
      }
      
      setNewCommentBody('');
      fetchComments();
    } catch (err) {
      setError(err instanceof Error ? err.message : '코멘트 작성 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleStatus = async (commentId: string, currentStatus: 'open' | 'resolved') => {
    if (!projectId || !agiId) return;
    
    try {
      const resolvedPath = projectId 
        ? `/api/projects/${projectId}/agile/${agiId}/objective/comments/${commentId}`
        : `/api/agile/${agiId}/objective/comments/${commentId}`;

      const response = await fetch(resolvedPath, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: currentStatus === 'open' ? 'resolved' : 'open' }),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to update comment status: ${response.status}`);
      }
      
      fetchComments();
    } catch (err) {
      setError(err instanceof Error ? err.message : '코멘트 상태 변경 실패');
    }
  };

  const filteredComments = comments.filter(c => {
    if (filter === 'all') return true;
    return c.status === filter;
  });

  return (
    <Card className="flex flex-col h-full border-l-0 rounded-none border-y-0 border-r-0">
      <CardHeader className="pb-3 border-b px-4 py-3 bg-muted/10 shrink-0 flex flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm font-semibold flex items-center gap-2 m-0">
            <MessageSquare className="h-4 w-4" /> Comments
          </CardTitle>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex bg-muted p-0.5 rounded-md">
            <button
              onClick={() => setFilter('all')}
              className={`px-2 py-1 text-xs rounded-sm transition-colors ${filter === 'all' ? 'bg-background shadow-sm' : 'text-muted-foreground hover:bg-background/50'}`}
            >
              All
            </button>
            <button
              onClick={() => setFilter('open')}
              className={`px-2 py-1 text-xs rounded-sm transition-colors ${filter === 'open' ? 'bg-background shadow-sm text-blue-600' : 'text-muted-foreground hover:bg-background/50'}`}
            >
              Open
            </button>
            <button
              onClick={() => setFilter('resolved')}
              className={`px-2 py-1 text-xs rounded-sm transition-colors ${filter === 'resolved' ? 'bg-background shadow-sm text-green-600' : 'text-muted-foreground hover:bg-background/50'}`}
            >
              Resolved
            </button>
          </div>
          {onCollapse && (
            <button
              type="button"
              onClick={onCollapse}
              className="h-7 w-7 rounded-md border bg-background hover:bg-accent/40 text-muted-foreground flex items-center justify-center"
              aria-label="코멘트 패널 접기"
              title="코멘트 패널 접기"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </CardHeader>
      
      <CardContent className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {error && (
          <div className="px-3 py-2 text-xs text-red-600 border border-red-200 bg-red-50 rounded-md">
            {error}
          </div>
        )}
        
        {loading && comments.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : filteredComments.length === 0 ? (
          <div className="text-center py-8 text-sm text-muted-foreground border border-dashed rounded-md">
            {filter === 'all' ? '코멘트가 없습니다.' : `해당 상태(${filter})의 코멘트가 없습니다.`}
          </div>
        ) : (
          <div className="space-y-3">
            {filteredComments.map((comment) => (
              <div 
                key={comment.id} 
                className={`text-sm rounded-md border p-3 ${comment.status === 'resolved' ? 'bg-muted/30 opacity-70' : 'bg-background'}`}
              >
                <div className="flex justify-between items-start mb-2 gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-xs">{comment.author}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {new Date(comment.createdAt).toLocaleString(undefined, {
                        dateStyle: 'short',
                        timeStyle: 'short'
                      })}
                    </span>
                  </div>
                  <button
                    onClick={() => handleToggleStatus(comment.id, comment.status)}
                    className="text-xs flex items-center justify-center p-1 rounded-md hover:bg-muted text-muted-foreground"
                    title={comment.status === 'open' ? 'Mark as resolved' : 'Reopen'}
                  >
                    {comment.status === 'open' ? (
                      <Check className="h-3 w-3 text-green-600" />
                    ) : (
                      <RotateCcw className="h-3 w-3" />
                    )}
                  </button>
                </div>
                <div className="whitespace-pre-wrap break-words text-slate-700">
                  {comment.body}
                </div>
                {comment.status === 'resolved' && (
                  <div className="mt-2 text-[10px] font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded-sm inline-block">
                    Resolved
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
      
      <div className="p-3 border-t bg-muted/5 shrink-0">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <textarea
            value={newCommentBody}
            onChange={(e) => setNewCommentBody(e.target.value)}
            placeholder="코멘트 작성..."
            className="w-full text-sm min-h-[60px] max-h-[150px] rounded-md border border-input bg-background px-3 py-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            disabled={isSubmitting}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={isSubmitting || !newCommentBody.trim()}>
              {isSubmitting ? '작성 중...' : '작성'}
            </Button>
          </div>
        </form>
      </div>
    </Card>
  );
}
