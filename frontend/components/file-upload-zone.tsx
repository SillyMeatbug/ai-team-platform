'use client'

import { useState, useCallback } from 'react'
import { Upload, X, FileText, Image, File } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface UploadedFile {
  id: string
  name: string
  size: string
  type: string
  progress: number
}

interface FileUploadZoneProps {
  onUpload?: (files: File[]) => void
  multiple?: boolean
  accept?: string
  uploadedFiles?: UploadedFile[]
  onRemove?: (id: string) => void
}

export function FileUploadZone({
  onUpload,
  multiple = true,
  accept = '.pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.fig',
  uploadedFiles = [],
  onRemove,
}: FileUploadZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragOver(false)
      const files = Array.from(e.dataTransfer.files)
      onUpload?.(files)
    },
    [onUpload]
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }, [])

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      onUpload?.(files)
      e.target.value = ''
    },
    [onUpload]
  )

  const getFileIcon = (type: string) => {
    if (type.startsWith('image/') || type.includes('png') || type.includes('jpg')) {
      return <Image className="w-4 h-4 text-primary" />
    }
    if (type.includes('pdf')) {
      return <FileText className="w-4 h-4 text-red-400" />
    }
    return <File className="w-4 h-4 text-muted-foreground" />
  }

  return (
    <div className="space-y-3">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'relative border-2 border-dashed rounded-lg p-6 transition-all duration-200',
          isDragOver
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50'
        )}
      >
        <input
          type="file"
          multiple={multiple}
          accept={accept}
          onChange={handleFileSelect}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          aria-label="Upload files"
        />
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="p-3 rounded-full bg-secondary">
            <Upload className="w-5 h-5 text-muted-foreground" />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground">
              Drop files here or click to upload
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              PDF, DOC, TXT, PNG, JPG, Figma files supported
            </p>
          </div>
        </div>
      </div>

      {uploadedFiles.length > 0 && (
        <div className="space-y-2">
          {uploadedFiles.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-3 p-3 rounded-lg bg-secondary/50 border border-border/50"
            >
              {getFileIcon(file.type)}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">
                  {file.name}
                </p>
                <p className="text-xs text-muted-foreground">{file.size}</p>
              </div>
              {file.progress < 100 ? (
                <div className="w-16 h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-300"
                    style={{ width: `${file.progress}%` }}
                  />
                </div>
              ) : (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  onClick={() => onRemove?.(file.id)}
                  aria-label={`Remove ${file.name}`}
                >
                  <X className="w-4 h-4" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
