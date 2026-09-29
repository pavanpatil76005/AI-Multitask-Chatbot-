'use client';

import React, { useRef, useState } from 'react';

export interface UploadedFile {
  id?: number;
  file: File;
  filename: string;
  fileType: string;
  formattedSize: string;
  status: 'selected' | 'uploading' | 'completed' | 'failed';
  progress?: number;
  error?: string;
  extracted?: {
    id: number;
    text: string;
    statistics?: Record<string, unknown>;
  };
}

interface FileUploadZoneProps {
  onFileSelected: (file: File) => Promise<void>;
  disabled?: boolean;
  maxSize?: number;
  supportedTypes?: string[];
}

const SUPPORTED_TYPES = [
  'application/pdf',
  'text/csv',
  'text/plain',
  'text/markdown',
];

const MAX_SIZE = 50 * 1024 * 1024; // 50 MB for direct upload
const MAX_DISPLAY_SIZE = 500 * 1024 * 1024;

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 10) / 10 + ' ' + sizes[i];
}

function getFileType(file: File): string {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  const typeMap: Record<string, string> = {
    '.pdf': 'PDF',
    '.csv': 'CSV',
    '.txt': 'TXT',
    '.md': 'Markdown',
  };
  return typeMap[ext] || 'File';
}

export function FileUploadZone({
  onFileSelected,
  disabled = false,
  maxSize = MAX_SIZE,
  supportedTypes = SUPPORTED_TYPES,
}: FileUploadZoneProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<UploadedFile | null>(null);
  const [error, setError] = useState<string>('');
  const dragCounter = useRef(0);

  function validateFile(file: File): { valid: boolean; error?: string } {
    if (!supportedTypes.includes(file.type)) {
      return {
        valid: false,
        error: `Unsupported file: ${file.name}. Use PDF, CSV, TXT, or Markdown.`,
      };
    }

    if (file.size > maxSize) {
      return {
        valid: false,
        error: `File too large: ${formatFileSize(file.size)}. Max: ${formatFileSize(maxSize)}.`,
      };
    }

    if (file.size === 0) {
      return { valid: false, error: 'File is empty.' };
    }

    return { valid: true };
  }

  function handleFile(file: File) {
    setError('');
    const validation = validateFile(file);

    if (!validation.valid) {
      setError(validation.error || 'Invalid file.');
      return;
    }

    const uploadedFile: UploadedFile = {
      file,
      filename: file.name,
      fileType: getFileType(file),
      formattedSize: formatFileSize(file.size),
      status: 'selected',
    };

    setSelectedFile(uploadedFile);
  }

  function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
    }
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) {
      setIsDragging(false);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounter.current = 0;

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFile(files[0]);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLDivElement>) {
    const files = Array.from(e.clipboardData.files);
    if (files.length > 0) {
      handleFile(files[0]);
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) {
      handleFile(files[0]);
    }
    e.target.value = '';
  }

  async function handleUpload() {
    if (!selectedFile) return;

    setSelectedFile((prev) => (prev ? { ...prev, status: 'uploading', progress: 0 } : null));
    setError('');

    try {
      await onFileSelected(selectedFile.file);
      setSelectedFile((prev) =>
        prev ? { ...prev, status: 'completed', progress: 100 } : null
      );
      // Clear after success
      setTimeout(() => setSelectedFile(null), 2000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Upload failed';
      setError(errorMsg);
      setSelectedFile((prev) => (prev ? { ...prev, status: 'failed', error: errorMsg } : null));
    }
  }

  function handleRemove() {
    setSelectedFile(null);
    setError('');
  }

  function handleRetry() {
    if (selectedFile) {
      setSelectedFile((prev) => (prev ? { ...prev, status: 'selected', error: undefined } : null));
      setError('');
    }
  }

  if (!selectedFile && !error) {
    return (
      <div
        className={`rounded-lg border-2 border-dashed p-6 transition cursor-pointer ${
          isDragging
            ? 'border-blue-400 bg-blue-900/20'
            : 'border-zinc-600 bg-zinc-900/30 hover:border-zinc-500'
        }`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onPaste={handlePaste}
        onClick={() => !disabled && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Upload file"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.csv,.txt,.md"
          onChange={handleInputChange}
          disabled={disabled}
          className="hidden"
          aria-hidden="true"
        />

        <div className="text-center">
          <div className="text-2xl mb-2">📄</div>
          <div className="font-medium">Drop file here or click</div>
          <div className="text-sm text-zinc-400 mt-1">Ctrl+V to paste • PDF, CSV, TXT, Markdown</div>
          <div className="text-xs text-zinc-500 mt-2">Max {formatFileSize(MAX_DISPLAY_SIZE)}</div>
        </div>
      </div>
    );
  }

  if (selectedFile) {
    return (
      <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-4">
        <div className="flex items-center justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <div className="font-medium text-white truncate">{selectedFile.filename}</div>
            <div className="flex gap-3 mt-1 text-xs text-zinc-400">
              <span>{selectedFile.fileType}</span>
              <span>{selectedFile.formattedSize}</span>
            </div>
          </div>
          {selectedFile.status !== 'uploading' && (
            <button
              onClick={handleRemove}
              className="text-zinc-400 hover:text-white text-sm underline whitespace-nowrap"
              type="button"
            >
              Remove
            </button>
          )}
        </div>

        {selectedFile.status === 'uploading' && (
          <div className="space-y-2 mb-3">
            <div className="flex justify-between text-xs text-zinc-400">
              <span>Uploading...</span>
              <span>{Math.round(selectedFile.progress || 0)}%</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-2">
              <div
                className="bg-blue-500 h-full rounded-full transition-all"
                style={{ width: `${selectedFile.progress || 0}%` }}
              />
            </div>
          </div>
        )}

        {selectedFile.status === 'completed' && (
          <div className="text-green-400 text-sm mb-2">✓ Upload completed</div>
        )}

        {selectedFile.status === 'failed' && selectedFile.error && (
          <div className="text-red-400 text-sm mb-3">{selectedFile.error}</div>
        )}

        {(selectedFile.status === 'selected' || selectedFile.status === 'failed') && (
          <div className="flex gap-2">
            <button
              onClick={handleUpload}
              disabled={disabled}
              className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-zinc-600 text-white text-sm font-medium rounded transition"
              type="button"
            >
              Upload
            </button>
            <button
              onClick={handleRemove}
              className="px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-white text-sm rounded transition"
              type="button"
            >
              Cancel
            </button>
          </div>
        )}

        {selectedFile.status === 'failed' && (
          <button
            onClick={handleRetry}
            className="w-full px-3 py-2 bg-orange-600 hover:bg-orange-700 text-white text-sm font-medium rounded transition"
            type="button"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return null;
}

