import { useState } from 'react';

import type { useEditorActions } from '../hooks/useEditorActions.js';
import type { EditorState } from '../office/editor/editorState.js';
import { Button } from './ui/Button.js';

interface EditActionBarProps {
  editor: ReturnType<typeof useEditorActions>;
  editorState: EditorState;
}

export function EditActionBar({ editor, editorState: es }: EditActionBarProps) {
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const undoDisabled = es.undoStack.length === 0;
  const redoDisabled = es.redoStack.length === 0;

  return (
    <div className="absolute top-8 left-1/2 -translate-x-1/2 z-10 flex gap-4 items-center pixel-panel p-4">
      <Button
        variant={undoDisabled ? 'disabled' : 'default'}
        size="md"
        onClick={undoDisabled ? undefined : editor.handleUndo}
        title="실행 취소 (Ctrl+Z)"
      >
        취소
      </Button>
      <Button
        variant={redoDisabled ? 'disabled' : 'default'}
        size="md"
        onClick={redoDisabled ? undefined : editor.handleRedo}
        title="다시 실행 (Ctrl+Y)"
      >
        다시
      </Button>
      <Button variant="default" size="md" onClick={editor.handleSave} title="배치 저장">
        저장
      </Button>
      {!showResetConfirm ? (
        <Button
          variant="default"
          size="md"
          onClick={() => setShowResetConfirm(true)}
          title="마지막 저장 상태로 초기화"
        >
          초기화
        </Button>
      ) : (
        <div className="flex gap-4 items-center">
          <span className="text-base text-reset-text">Reset?</span>
          <Button
            variant="default"
            size="md"
            className="bg-danger text-white"
            onClick={() => {
              setShowResetConfirm(false);
              editor.handleReset();
            }}
          >
            Yes
          </Button>
          <Button variant="default" size="md" onClick={() => setShowResetConfirm(false)}>
            No
          </Button>
        </div>
      )}
    </div>
  );
}
