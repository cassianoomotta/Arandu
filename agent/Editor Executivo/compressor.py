import re
from typing import List

# Common stop words in Portuguese and English
STOPWORDS = {
    # Portuguese
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "no", "na", "nos", "nas",
    "ao", "aos", "à", "às", "em", "para", "por", "com", "sem", "sob", "sobre", "atrás", "como", "que", "se", "o",
    "é", "são", "foi", "foram", "era", "eram", "ser", "estar", "ter", "haver", "fazer", "dizer", "este", "esta",
    "estes", "estas", "isto", "isso", "aquilo", "ele", "ela", "eles", "elas", "me", "te", "se", "nos", "vos",
    "mas", "porém", "todavia", "contudo", "entretanto", "mais", "menos", "muito", "pouco", "já", "ainda", "também",
    # English
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of", "to", "in", "on", "at", "by", "for", "with",
    "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "from", "up",
    "down", "out", "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now"
}

def split_into_sentences(text: str) -> List[str]:
    """Splits a block of text into sentences using simple regex patterns."""
    # Split on periods/exclamation/question marks followed by whitespace and uppercase letter
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def get_word_count(text: str) -> int:
    """Returns the word count of a given string."""
    return len(re.findall(r'\b\w+\b', text))

def compress_text(text: str, min_words: int = 800, max_words: int = 1200) -> str:
    """
    Compresses text locally using extractive summarization.
    Ranks sentences by term frequency density, selects the top sentences
    until the word count falls within the [min_words, max_words] range,
    and returns them in their original order.
    """
    total_words = get_word_count(text)
    if total_words <= max_words:
        return text

    sentences = split_into_sentences(text)
    if not sentences:
        return text

    # Count term frequencies (excluding stopwords)
    term_frequencies = {}
    for sentence in sentences:
        words = re.findall(r'\b\w+\b', sentence.lower())
        for word in words:
            if word not in STOPWORDS and len(word) > 2:
                term_frequencies[word] = term_frequencies.get(word, 0) + 1

    # Score sentences based on density of high frequency words
    sentence_scores = []
    for idx, sentence in enumerate(sentences):
        words = re.findall(r'\b\w+\b', sentence.lower())
        meaningful_words = [w for w in words if w in term_frequencies]
        
        if not words:
            score = 0.0
        else:
            # Sum frequencies of meaningful terms and normalize by sentence length
            freq_sum = sum(term_frequencies[w] for w in meaningful_words)
            score = freq_sum / len(words)
            
        sentence_scores.append((idx, score, sentence))

    # Sort sentences by score descending to pick the best ones
    sentence_scores.sort(key=lambda x: x[1], reverse=True)

    # Accumulate sentences until we cross the max_words limit or run out of sentences
    selected_indices = []
    current_word_count = 0
    
    # Always try to include the first sentence of the article for context introduction
    first_sentence_included = False
    for item in sentence_scores:
        if item[0] == 0:
            selected_indices.append(0)
            current_word_count += get_word_count(item[2])
            first_sentence_included = True
            break

    for idx, score, sentence in sentence_scores:
        if idx == 0 and first_sentence_included:
            continue
            
        word_count = get_word_count(sentence)
        if current_word_count + word_count <= max_words:
            selected_indices.append(idx)
            current_word_count += word_count
        elif current_word_count < min_words:
            # If we are still below the minimum target, add this sentence anyway
            selected_indices.append(idx)
            current_word_count += word_count
            if current_word_count >= min_words:
                break
        else:
            break

    # Sort selected indices back to preserve reading order/logical coherence
    selected_indices.sort()
    compressed_sentences = [sentences[i] for i in selected_indices]
    
    return " ".join(compressed_sentences)
