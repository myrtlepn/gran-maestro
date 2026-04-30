/**
 * Minimal Deno type declarations for type-checking in Node.js/tsc environments.
 *
 * When running under Deno these are provided natively. This shim allows
 * `npx tsc --noEmit` to validate the code without a full Deno installation.
 */

declare namespace Deno {
  interface CommandOptions {
    args?: string[];
    cwd?: string;
    stdin?: 'piped' | 'inherit' | 'null';
    stdout?: 'piped' | 'inherit' | 'null';
    stderr?: 'piped' | 'inherit' | 'null';
  }

  interface CommandOutput {
    code: number;
    stdout: Uint8Array;
    stderr: Uint8Array;
  }

  interface ChildProcess {
    output(): Promise<CommandOutput>;
    kill(signal?: string): void;
  }

  class Command {
    constructor(command: string, options?: CommandOptions);
    spawn(): ChildProcess;
    output(): Promise<CommandOutput>;
    outputSync(): CommandOutput;
  }

  interface Env {
    get(key: string): string | undefined;
    set(key: string, value: string): void;
    delete(key: string): void;
    has(key: string): boolean;
    toObject(): Record<string, string>;
  }

  const env: Env;

  interface MkdirOptions {
    recursive?: boolean;
  }

  interface RemoveOptions {
    recursive?: boolean;
  }

  interface FileInfo {
    mtime: Date | null;
    isDirectory: boolean;
    isFile: boolean;
  }

  interface DirEntry {
    name: string;
    isFile: boolean;
    isDirectory: boolean;
    isSymlink: boolean;
  }

  function writeTextFile(path: string, data: string): Promise<void>;
  function readTextFile(path: string): Promise<string>;
  function rename(oldPath: string, newPath: string): Promise<void>;
  function mkdir(path: string, options?: MkdirOptions): Promise<void>;
  function remove(path: string, options?: RemoveOptions): Promise<void>;
  function stat(path: string): Promise<FileInfo>;
  function readDir(path: string): AsyncIterable<DirEntry>;
  function cwd(): string;

  interface FsWatcher extends AsyncIterable<FsEvent> {
    close(): void;
  }

  interface FsEvent {
    kind: 'create' | 'modify' | 'remove' | 'access' | 'other';
    paths: string[];
  }

  function watchFs(paths: string | string[], options?: { recursive?: boolean }): FsWatcher;

  namespace errors {
    class AlreadyExists extends Error {}
  }

  function test(name: string, fn: () => void | Promise<void>): void;
}
