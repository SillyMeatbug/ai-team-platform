'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { LanguageToggle } from '@/components/language-toggle'
import { useLocale } from '@/components/locale-provider'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { FileUploadZone } from '@/components/file-upload-zone'
import { AgentSelector } from '@/components/agent-selector'
import { addProjectAgent, createProject, getAllAgents, uploadProjectFile } from '@/lib/api'
import type { Agent } from '@/lib/types'
import { ArrowLeft, ArrowRight, Check, Sparkles, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { mergeAgentsForUi } from '@/lib/ui-demo-agents'
import { toast } from 'sonner'

type Step = 1 | 2 | 3

interface UploadedFile {
  id: string
  name: string
  size: string
  type: string
  progress: number
  rawFile: File
}

export default function CreateProjectPage() {
  const router = useRouter()
  const { t } = useLocale()
  const [step, setStep] = useState<Step>(1)
  const [isCreating, setIsCreating] = useState(false)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isCryptoEnabled, setIsCryptoEnabled] = useState(false)
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([])
  const [availableAgents, setAvailableAgents] = useState<Agent[]>([])

  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const productAgents = useMemo(
    () =>
      availableAgents.filter(
        (a) =>
          ![
            'technical_analyst',
            'onchain_analyst',
            'sentiment_analyst',
            'risk_manager',
            'crypto_interpreter',
          ].includes(
            a.role
          )
      ),
    [availableAgents]
  )
  const cryptoAgents = useMemo(
    () =>
      availableAgents.filter((a) =>
        [
          'technical_analyst',
          'onchain_analyst',
          'sentiment_analyst',
          'risk_manager',
          'crypto_interpreter',
        ].includes(
          a.role
        )
      ),
    [availableAgents]
  )
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null)

  const isStep1Valid = name.trim().length >= 3
  const isStep2Valid = selectedAgents.length >= 1
  const isDemoAgentPool = availableAgents.some((a) => a.id.startsWith('ui-demo-'))

  const handleFileUpload = useCallback((files: File[]) => {
    const newFiles = files.map((file) => ({
      id: `file-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      size: formatFileSize(file.size),
      type: file.type || file.name.split('.').pop() || 'unknown',
      progress: 100,
      rawFile: file,
    }))

    setUploadedFiles((prev) => [...prev, ...newFiles])
  }, [])

  const handleRemoveFile = useCallback((id: string) => {
    setUploadedFiles((prev) => prev.filter((f) => f.id !== id))
  }, [])

  const handleAgentSelect = useCallback((agentId: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agentId)
        ? prev.filter((id) => id !== agentId)
        : [...prev, agentId]
    )
  }, [])

  const handleNext = async () => {
    if (step === 1 && isStep1Valid) {
      setStep(2)
    } else if (step === 2 && isStep2Valid) {
      if (isDemoAgentPool) {
        toast.error(t('createProject.toastDemoBlocked'))
        return
      }
      setIsCreating(true)
      try {
        const project = await createProject({
          name: name.trim(),
          description: description.trim() || undefined,
          is_crypto_enabled: isCryptoEnabled,
        })
        setCreatedProjectId(project.id)
        for (const agentId of selectedAgents) {
          await addProjectAgent(project.id, agentId)
        }
        for (const file of uploadedFiles) {
          await uploadProjectFile(project.id, file.rawFile, 'brief')
        }
        setIsCreating(false)
        toast.success(t('createProject.toastCreated'))
        setStep(3)
      } catch (e) {
        setIsCreating(false)
        toast.error(`${t('createProject.toastCreateFailed')}: ${(e as Error).message}`)
      }
    }
  }

  const handleBack = () => {
    if (step === 2) {
      setStep(1)
    }
  }

  useEffect(() => {
    if (step === 3 && createdProjectId) {
      const timer = setTimeout(() => {
        router.push(`/project/${createdProjectId}`)
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [step, createdProjectId, router])

  useEffect(() => {
    let mounted = true
    const loadAgents = async () => {
      try {
        const agents = await getAllAgents()
        if (mounted) setAvailableAgents(mergeAgentsForUi(agents))
      } catch (e) {
        if (mounted) setAvailableAgents(mergeAgentsForUi([]))
        toast.error(`${t('createProject.toastAgentsFailed')}: ${(e as Error).message}`)
      }
    }
    void loadAgents()
    return () => {
      mounted = false
    }
  }, [t])

  useEffect(() => {
    if (isCryptoEnabled) return
    const allowedIds = new Set(productAgents.map((a) => a.id))
    setSelectedAgents((prev) => {
      const next = prev.filter((id) => allowedIds.has(id))
      if (next.length === prev.length) return prev
      return next
    })
  }, [isCryptoEnabled, productAgents])

  const launchLabel =
    selectedAgents.length === 1
      ? t('createProject.launch', { count: selectedAgents.length })
      : t('createProject.launch_plural', { count: selectedAgents.length })

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border sticky top-0 bg-background/95 backdrop-blur-sm z-10">
        <div className="mx-auto max-w-6xl px-4 py-4 sm:px-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-4 min-w-0">
              <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground shrink-0" asChild>
                <Link href="/">
                  <ArrowLeft className="w-5 h-5" />
                  <span className="sr-only">{t('createProject.backSr')}</span>
                </Link>
              </Button>
              <h1 className="font-semibold text-lg text-foreground truncate">{t('createProject.title')}</h1>
            </div>
            <LanguageToggle />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 pt-6 sm:px-6">
        <div className="flex items-center gap-2">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center flex-1">
              <div
                className={cn(
                  'flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium transition-colors',
                  step >= s ? 'gradient-accent text-white' : 'bg-secondary text-muted-foreground'
                )}
              >
                {step > s ? <Check className="w-4 h-4" /> : s}
              </div>
              {s < 3 && (
                <div
                  className={cn(
                    'flex-1 h-0.5 mx-2 transition-colors',
                    step > s ? 'bg-primary' : 'bg-secondary'
                  )}
                />
              )}
            </div>
          ))}
        </div>
        <div className="flex justify-between mt-2 text-xs text-muted-foreground">
          <span>{t('createProject.stepInfo')}</span>
          <span>{t('createProject.stepTeam')}</span>
          <span>{t('createProject.stepDone')}</span>
        </div>
      </div>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {step === 1 && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-foreground mb-1">
                {t('createProject.sectionInfoTitle')}
              </h2>
              <p className="text-sm text-muted-foreground">{t('createProject.sectionInfoSubtitle')}</p>
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <label htmlFor="name" className="text-sm font-medium text-foreground">
                  {t('createProject.nameLabel')} <span className="text-destructive">*</span>
                </label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('createProject.namePlaceholder')}
                  className="bg-secondary border-border focus:border-primary"
                />
                {name.length > 0 && name.length < 3 && (
                  <p className="text-xs text-destructive">{t('createProject.nameTooShort')}</p>
                )}
              </div>

              <div className="space-y-2">
                <label htmlFor="description" className="text-sm font-medium text-foreground">
                  {t('createProject.descriptionLabel')}{' '}
                  <span className="text-muted-foreground">{t('common.optional')}</span>
                </label>
                <Textarea
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('createProject.descriptionPlaceholder')}
                  rows={3}
                  maxLength={500}
                  className="bg-secondary border-border focus:border-primary resize-none"
                />
                <p className="text-xs text-muted-foreground text-right">
                  {description.length}/500
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">
                  {t('createProject.filesLabel')}{' '}
                  <span className="text-muted-foreground">{t('common.optional')}</span>
                </label>
                <p className="text-xs text-muted-foreground mb-2">{t('createProject.filesHint')}</p>
                <FileUploadZone
                  onUpload={handleFileUpload}
                  uploadedFiles={uploadedFiles}
                  onRemove={handleRemoveFile}
                />
              </div>

              <div className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">Это крипто-проект?</p>
                    <p className="text-xs text-muted-foreground">
                      Включает крипто-агентов и вкладку Paper Trading
                    </p>
                  </div>
                  <Switch checked={isCryptoEnabled} onCheckedChange={setIsCryptoEnabled} />
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-4">
              <Button
                onClick={() => void handleNext()}
                disabled={!isStep1Valid}
                className="gradient-accent text-white border-0 hover:opacity-90 disabled:opacity-50"
              >
                {t('common.continue')}
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-foreground mb-1">
                {t('createProject.sectionTeamTitle')}
              </h2>
              <p className="text-sm text-muted-foreground">{t('createProject.sectionTeamSubtitle')}</p>
              {isDemoAgentPool && (
                <p className="mt-3 text-sm rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-200/90">
                  {t('createProject.demoBanner')}
                </p>
              )}
            </div>

            <div className="space-y-4">
              <div>
                <h3 className="mb-2 text-sm font-medium text-foreground">Product Team</h3>
                <AgentSelector
                  availableAgents={productAgents}
                  selectedAgents={selectedAgents}
                  onSelect={handleAgentSelect}
                />
              </div>
              {isCryptoEnabled && (
                <div>
                  <h3 className="mb-2 text-sm font-medium text-foreground">Crypto Trading Team</h3>
                  <AgentSelector
                    availableAgents={cryptoAgents}
                    selectedAgents={selectedAgents}
                    onSelect={handleAgentSelect}
                  />
                </div>
              )}
            </div>

            <div className="flex items-center justify-between pt-4">
              <Button
                variant="outline"
                onClick={handleBack}
                className="border-border text-foreground hover:bg-secondary"
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                {t('common.back')}
              </Button>
              <Button
                onClick={() => void handleNext()}
                disabled={!isStep2Valid || isCreating}
                className="gradient-accent text-white border-0 hover:opacity-90 disabled:opacity-50"
              >
                {isCreating ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {t('createProject.creating')}
                  </>
                ) : (
                  <>
                    {launchLabel}
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </>
                )}
              </Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="p-4 rounded-full gradient-accent mb-4">
              <Sparkles className="w-8 h-8 text-white" />
            </div>
            <h2 className="text-2xl font-semibold text-foreground mb-2">{t('createProject.successTitle')}</h2>
            <p className="text-muted-foreground text-center max-w-sm mb-6">
              {t('createProject.successSubtitle')}
            </p>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('createProject.redirecting')}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
