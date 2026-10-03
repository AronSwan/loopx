import { useRef, useState, type SetStateAction } from "react";
import type { WorkspaceImageAttachment } from "./personal-workspace-model";

interface ConversationInputState {
  sending: boolean;
  steering: boolean;
  actionFeedback: string | null;
  imageAttachments: WorkspaceImageAttachment[];
  imageAttachmentError: string | null;
  loopxMessageReceipt: string;
}

const emptyInput: ConversationInputState = {
  sending: false,
  steering: false,
  actionFeedback: null,
  imageAttachments: [],
  imageAttachmentError: null,
  loopxMessageReceipt: "",
};

// An async callback keeps the key from its originating render. Leaving a
// conversation does not cancel delivery or let its late receipt edit a peer.
// This state is presentation only; Session/Turn ingress still owns effects.
export function useConversationInputState(key: string) {
  const [inputs, setInputs] = useState<Record<string, ConversationInputState>>({});
  const visibleKey = useRef(key);
  visibleKey.current = key;

  function setter<K extends keyof ConversationInputState>(field: K) {
    return (value: SetStateAction<ConversationInputState[K]>) => setInputs((current) => {
      const input = current[key] ?? emptyInput;
      const next = typeof value === "function"
        ? (value as (previous: ConversationInputState[K]) => ConversationInputState[K])(input[field])
        : value;
      return { ...current, [key]: { ...input, [field]: next } };
    });
  }

  return {
    ...(inputs[key] ?? emptyInput),
    setSending: setter("sending"),
    setSteering: setter("steering"),
    setActionFeedback: setter("actionFeedback"),
    setImageAttachments: setter("imageAttachments"),
    setImageAttachmentError: setter("imageAttachmentError"),
    setLoopxMessageReceipt: setter("loopxMessageReceipt"),
    isCurrentConversation: () => visibleKey.current === key,
  };
}
