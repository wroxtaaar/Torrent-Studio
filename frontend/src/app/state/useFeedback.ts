import { api } from '../../api/client.ts';
import { useAppDialogState } from './useAppDialogState.ts';

export function useFeedback({ feedbackMessage, setFeedbackError, setFeedbackSubmitting, setFeedbackSuccess, feedbackType, feedbackRating, feedbackName, setFeedbackMessage, setFeedbackName, setFeedbackRating }: Pick<ReturnType<typeof useAppDialogState>, 'feedbackMessage' | 'setFeedbackError' | 'setFeedbackSubmitting' | 'setFeedbackSuccess' | 'feedbackType' | 'feedbackRating' | 'feedbackName' | 'setFeedbackMessage' | 'setFeedbackName' | 'setFeedbackRating'>) {
  const submitFeedback = async () => {
    const message = feedbackMessage.trim();
    if (message.length < 5) {
      setFeedbackError('Please write at least a few words.');
      return;
    }

    setFeedbackSubmitting(true);
    setFeedbackError('');
    setFeedbackSuccess('');
    try {
      await api.submitFeedback({
        type: feedbackType,
        rating: feedbackType === 'review' ? feedbackRating : undefined,
        message,
        name: feedbackName.trim() || undefined,
      });
      setFeedbackMessage('');
      setFeedbackName('');
      setFeedbackRating(5);
      setFeedbackSuccess('Thanks! Your feedback was sent successfully.');
    } catch (error: any) {
      setFeedbackError(String(error?.message || 'Could not send feedback. Please try again.'));
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  return {
    submitFeedback,
  };
}
