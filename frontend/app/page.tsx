'use client'

import { useCallback, useEffect, useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { toast } from 'sonner'
import { LanguageToggle } from '@/components/language-toggle'
import { useLocale } from '@/components/locale-provider'
import { Button } from '@/components/ui/button'
import { ProjectCard } from '@/components/project-card'
import { deleteProject, getProjects } from '@/lib/api'
import type { Project } from '@/lib/types'
import { Plus, FolderPlus } from 'lucide-react'

export default function DashboardPage() {
  const { t } = useLocale()
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    const safetyMs = 22_000
    const safetyId = window.setTimeout(() => {
      setIsLoading((loading) => {
        if (loading) {
          toast.error(t('dashboard.loadTimeout'))
          return false
        }
        return loading
      })
    }, safetyMs)

    const load = async () => {
      try {
        const data = await getProjects(ac.signal)
        setProjects(data)
      } catch (e) {
        const aborted =
          (e instanceof DOMException && e.name === 'AbortError') ||
          (e instanceof Error && e.name === 'AbortError')
        if (aborted) return
        const msg = e instanceof Error ? e.message : t('dashboard.loadFailed')
        toast.error(msg)
      } finally {
        window.clearTimeout(safetyId)
        setIsLoading(false)
      }
    }
    void load()
    return () => {
      window.clearTimeout(safetyId)
      ac.abort()
    }
  }, [t])

  const handleQuickDelete = useCallback(
    async (project: Project) => {
      const ok = window.confirm(`${t('project.deleteDialogTitle')}: "${project.name}"?`)
      if (!ok) return
      setDeletingProjectId(project.id)
      try {
        await deleteProject(project.id)
        setProjects((prev) => prev.filter((p) => p.id !== project.id))
        toast.success(t('project.toastProjectDeleted'))
      } catch (e) {
        toast.error(`${t('project.toastProjectDeleteFailed')}: ${(e as Error).message}`)
      } finally {
        setDeletingProjectId(null)
      }
    },
    [t]
  )

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border sticky top-0 bg-background/95 backdrop-blur-sm z-10">
        <div className="mx-auto max-w-6xl px-4 py-4 sm:px-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <Image
                src="/icon_favicon.png"
                alt=""
                width={56}
                height={56}
                className="size-12 shrink-0 object-contain sm:size-14"
                sizes="(min-width:640px) 56px, 48px"
                priority
              />
              <h1 className="font-semibold text-lg text-foreground truncate">
                {t('dashboard.title')}
              </h1>
            </div>
            <div className="flex items-center gap-2 sm:gap-3 shrink-0">
              <LanguageToggle />
              <Link href="/projects/new">
                <Button className="gradient-accent text-white border-0 hover:opacity-90">
                  <Plus className="w-4 h-4 sm:mr-2" />
                  <span className="hidden sm:inline">{t('dashboard.newProject')}</span>
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-foreground">{t('dashboard.yourProjects')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('dashboard.subtitle')}</p>
        </div>

        {isLoading ? (
          <div className="text-sm text-muted-foreground">{t('dashboard.loadingProjects')}</div>
        ) : projects.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onQuickDelete={handleQuickDelete}
                deleting={deletingProjectId === project.id}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-16 px-4">
            <div className="p-4 rounded-full bg-secondary/50 mb-4">
              <FolderPlus className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium text-foreground mb-2">{t('dashboard.emptyTitle')}</h3>
            <p className="text-sm text-muted-foreground text-center max-w-sm mb-6">
              {t('dashboard.emptySubtitle')}
            </p>
            <Link href="/projects/new">
              <Button className="gradient-accent text-white border-0 hover:opacity-90">
                <Plus className="w-4 h-4 mr-2" />
                {t('dashboard.createFirst')}
              </Button>
            </Link>
          </div>
        )}
      </main>
    </div>
  )
}
