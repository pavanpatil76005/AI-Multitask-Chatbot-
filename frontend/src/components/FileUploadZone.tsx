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

const MAX_SIZE = 500 * 1024 * 1024; // 500 MB for display
const MAX_DIRECT_UPLOAD = 50 * 1024 * 1024; // 50 MB actual backend limit

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
        error: `Unsupported file type: ${file.type}. Supported: PDF, CSV, TXT, Markdown.`,
      };
    }

    if (file.size > maxSize) {
      return {
        valid: false,
        error: `File too large: ${formatFileSize(file.size)}. Maximum: ${formatFileSize(maxSize)}.`,
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
    // Reset input so same file can be selected again
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

  function handleCancel() {
    handleRemove();
  }

  function handleRetry() {
    if (selectedFile) {
      setSelectedFile((prev) => (prev ? { ...prev, status: 'selected', error: undefined } : null));
      setError('');
    }
  }

  return (
    <div className="mb-4">
      <div
        className={`relative rounded-lg border-2 border-dashed p-6 transition ${
          isDragging
            ? 'border-blue-400 bg-blue-900/20'
            : 'border-slate-600 bg-slate-900/50 hover:border-slate-500'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onPaste={handlePaste}
        onClick={() => !disabled && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Drop files here or click to browse"
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

        {!selectedFile ? (
          <div className="text-center space-y-3">
            <div className="text-lg font-semibold text-white">Drop file here</div>
            <div className="text-sm text-slate-400">
              <span>Ctrl+V to paste</span>
              <span className="mx-2">•</span>
              <span>Choose File</span>
            </div>
            <div className="text-xs text-slate-500">
              PDF, CSV, TXT, Markdown • Up to 500 MB
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* File Info */}
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-white truncate">
                  {selectedFile.filename}
                </div>
                <div className="flex gap-4 mt-1 text-xs text-slate-400">
                  <span>{selectedFile.fileType}</span>
                  <span>{selectedFile.formattedSize}</span>
                </div>
              </div>
              {selectedFile.status !== 'uploading' && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemove();
                  }}
                  className="text-slate-400 hover:text-slate-200 text-sm underline"
                  type="button"
                >
                  Remove
                </button>
              )}
            </div>

            {/* Progress Bar */}
            {selectedFile.status === 'uploading' && selectedFile.progress !== undefined && (
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-slate-400">
                  <span>Uploading...</span>
                  <span>{Math.round(selectedFile.progress)}%</span>
                </div>
                <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
                  <div
                    className="bg-blue-500 h-full transition-all duration-300"
                    style={{ width: `${selectedFile.progress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Status Messages */}
            {selectedFile.status === 'completed' && (
              <div className="flex items-center gap-2 text-emerald-400 text-sm">
                <span>✓ Upload completed</span>
              </div>
            )}

            {selectedFile.status === 'failed' && selectedFile.error && (
              <div className="space-y-3">
                <div className="text-red-400 text-sm">✕ {selectedFile.error}</div>
                <div className="flex gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRetry();
                    }}
                    className="text-blue-400 hover:text-blue-300 text-sm underline"
                    type="button"
                  >
                    Retry
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCancel();
                    }}
                    className="text-slate-400 hover:text-slate-200 text-sm underline"
                    type="button"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Action Buttons */}
            {(selectedFile.status === 'selected' || selectedFile.status === 'failed') && (
              <div className="flex gap-2 pt-2">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleUpload();
                  }}
                  disabled={disabled}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white text-sm font-medium rounded transition"
                  type="button"
                >
                  Upload
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCancel();
                  }}
                  className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded transition"
                  type="button"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Global Error Message */}
      {error && !selectedFile && (
        <div className="mt-3 p-3 bg-red-900/30 border border-red-700 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Size Warning for Large Files */}
      {selectedFile && selectedFile.file.size > MAX_DIRECT_UPLOAD && (
        <div className="mt-3 p-3 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-400 text-sm">
          ⚠ Large files over 50 MB will use chunked upload. This may take longer.
        </div>
      )}
    </div>
  );
}
