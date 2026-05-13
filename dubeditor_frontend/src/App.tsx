import React, { useState } from 'react'
import ProjectList from './components/ProjectList'
import Editor from './components/Editor'
import TranslatePage from './components/TranslatePage'

type View =
  | { page: 'list' }
  | { page: 'editor';    projectId: number }
  | { page: 'translate'; projectId: number }

export default function App() {
  const [view, setView] = useState<View>({ page: 'list' })

  if (view.page === 'editor') {
    return (
      <Editor
        projectId={view.projectId}
        onBack={() => setView({ page: 'list' })}
        onTranslate={() => setView({ page: 'translate', projectId: view.projectId })}
      />
    )
  }

  if (view.page === 'translate') {
    return (
      <TranslatePage
        projectId={view.projectId}
        onBack={() => setView({ page: 'editor', projectId: view.projectId })}
      />
    )
  }

  return <ProjectList onOpen={id => setView({ page: 'editor', projectId: id })} />
}
