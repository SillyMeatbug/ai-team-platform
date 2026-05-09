'use client'

import { Button } from '@/components/ui/button'
import { FileText, Image, File, Figma, Download, Trash2 } from 'lucide-react'
import type { ProjectFile } from '@/lib/types'

interface ProjectFilesListProps {
  files: ProjectFile[]
  onDelete?: (id: string) => void
  onDownload?: (id: string) => void
}

const categoryLabels: Record<ProjectFile['category'], string> = {
  brief: 'Brief & Requirements',
  mockup: 'Mockups',
  reference: 'References',
  generated: 'Generated',
}

export function ProjectFilesList({ files, onDelete, onDownload }: ProjectFilesListProps) {
  const filesByCategory = files.reduce((acc, file) => {
    if (!acc[file.category]) acc[file.category] = []
    acc[file.category].push(file)
    return acc
  }, {} as Record<ProjectFile['category'], ProjectFile[]>)

  const getFileIcon = (type: ProjectFile['type']) => {
    switch (type) {
      case 'image':
        return <Image className="w-4 h-4 text-primary" />
      case 'pdf':
        return <FileText className="w-4 h-4 text-red-400" />
      case 'doc':
        return <FileText className="w-4 h-4 text-blue-400" />
      case 'figma':
        return <Figma className="w-4 h-4 text-purple-400" />
      default:
        return <File className="w-4 h-4 text-muted-foreground" />
    }
  }

  const categories = Object.keys(categoryLabels) as ProjectFile['category'][]

  return (
    <div className="space-y-6">
      {categories.map((category) => {
        const categoryFiles = filesByCategory[category]
        if (!categoryFiles || categoryFiles.length === 0) return null

        return (
          <div key={category}>
            <h4 className="text-sm font-medium text-muted-foreground mb-3">
              {categoryLabels[category]}
            </h4>
            <div className="space-y-2">
              {categoryFiles.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-secondary/50 border border-border/50 hover:border-border transition-colors group"
                >
                  {getFileIcon(file.type)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">
                      {file.name}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {file.size} &bull; {file.uploadedAt}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-foreground"
                      onClick={() => onDownload?.(file.id)}
                      aria-label={`Download ${file.name}`}
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => onDelete?.(file.id)}
                      aria-label={`Delete ${file.name}`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {files.length === 0 && (
        <div className="text-center py-12">
          <FolderOpen className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
          <p className="text-muted-foreground">No files uploaded yet</p>
        </div>
      )}
    </div>
  )
}

function FolderOpen(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2" />
    </svg>
  )
}
