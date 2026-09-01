> ## Documentation Index
> Fetch the complete documentation index at: https://docs.fish.audio/llms.txt
> Use this file to discover all available pages before exploring further.

# Emotion & Expression Control

> Make your AI voices express emotions naturally

export const AudioTranscript = ({voices = []}) => {
  const [selectedVoice, setSelectedVoice] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const audioRef = useRef(null);
  const dropdownRef = useRef(null);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const updateTime = () => setCurrentTime(audio.currentTime);
    const updateDuration = () => setDuration(audio.duration);
    const handleEnded = () => setIsPlaying(false);
    audio.addEventListener('timeupdate', updateTime);
    audio.addEventListener('loadedmetadata', updateDuration);
    audio.addEventListener('ended', handleEnded);
    return () => {
      audio.removeEventListener('timeupdate', updateTime);
      audio.removeEventListener('loadedmetadata', updateDuration);
      audio.removeEventListener('ended', handleEnded);
    };
  }, []);
  useEffect(() => {
    const handleClickOutside = event => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    if (isDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isDropdownOpen]);
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.load();
      setIsPlaying(false);
      setCurrentTime(0);
    }
  }, [selectedVoice]);
  const togglePlay = () => {
    if (isPlaying) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };
  const handleProgressChange = e => {
    const newTime = parseFloat(e.target.value);
    audioRef.current.currentTime = newTime;
    setCurrentTime(newTime);
  };
  const formatTime = time => {
    if (isNaN(time)) return '0:00';
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };
  const currentVoice = voices[selectedVoice];
  return <div className="border rounded-lg bg-card border-gray-200 dark:border-gray-800">
      {}
      <div className="grid grid-cols-3 items-center px-3 py-1.5 bg-muted border-b border-gray-200 dark:border-gray-800">
        <span className="text-xs font-medium">Listen to Page</span>

        <span className="text-xs font-semibold text-muted-foreground text-center">Powered by Fish Audio S2 Pro</span>

        {voices.length > 1 ? <div className="relative justify-self-end" ref={dropdownRef}>
            <button onClick={() => setIsDropdownOpen(!isDropdownOpen)} className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-muted hover:bg-gray-200 dark:hover:bg-gray-700 transition-all duration-200 cursor-pointer text-xs">
              <span className="text-muted-foreground">Voice:</span>
              <span className="font-medium">{voices[selectedVoice]?.name}</span>
              <svg className={`w-3 h-3 transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {isDropdownOpen && <div className="absolute right-0 mt-1 w-auto bg-white dark:bg-black border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden z-50">
                {voices.map((voice, index) => <button key={index} onClick={() => {
    setSelectedVoice(index);
    setIsDropdownOpen(false);
  }} className={`w-full px-3 py-1.5 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors flex items-center gap-2 ${index === selectedVoice ? 'bg-gray-100 dark:bg-gray-800 font-medium' : ''}`}>
                    {voice.id && <img src={`https://public-platform.r2.fish.audio/coverimage/${voice.id}`} alt={voice.name} className="w-5 h-5 rounded-full m-0 flex-shrink-0 object-cover" />}
                    <span className="flex-1 whitespace-nowrap">{voice.name}</span>
                  </button>)}
              </div>}
          </div> : <div className="justify-self-end" />}
      </div>

      {}
      <div className="px-3 py-1.5 bg-card">
        <audio ref={audioRef} src={currentVoice?.url} preload="metadata" />

        <div className="flex items-center gap-2">
          {}
          <button onClick={togglePlay} className="flex-shrink-0 w-6 h-6 flex items-center justify-center bg-gray-300 dark:bg-gray-600 text-gray-800 dark:text-gray-200 rounded-full hover:opacity-80 transition-opacity relative overflow-hidden" aria-label={isPlaying ? 'Pause' : 'Play'}>
            <div className="transition-transform duration-300 ease-in-out" style={{
    transform: isPlaying ? 'rotate(180deg)' : 'rotate(0deg)'
  }}>
              {isPlaying ? <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                </svg> : <svg className="w-3 h-3 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>}
            </div>
          </button>

          {}
          <div className="flex-1 flex items-center gap-2">
            <span className="text-xs font-mono text-gray-500 dark:text-gray-400 min-w-[35px]">
              {formatTime(currentTime)}
            </span>

            <div className="flex-1 relative h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div className="absolute top-0 left-0 h-full bg-gray-400 dark:bg-gray-500 transition-all duration-100" style={{
    width: `${duration ? currentTime / duration * 100 : 0}%`
  }} />
              <input type="range" min="0" max={duration || 0} value={currentTime} onChange={handleProgressChange} className="absolute top-0 left-0 w-full h-full opacity-0 cursor-pointer" />
            </div>
            <span className="text-xs font-mono text-gray-500 dark:text-gray-400 min-w-[35px]">
              {formatTime(duration)}
            </span>
          </div>
        </div>
      </div>
    </div>;
};

<AudioTranscript
  voices={[
  {
    "id": "8ef4a238714b45718ce04243307c57a7",
    "name": "E-girl",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/8ef4a238714b45718ce04243307c57a7.mp3"
  },
  {
    "id": "802e3bc2b27e49c2995d23ef70e6ac89",
    "name": "Energetic Male",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/802e3bc2b27e49c2995d23ef70e6ac89.mp3"
  },
  {
    "id": "933563129e564b19a115bedd57b7406a",
    "name": "Sarah",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/933563129e564b19a115bedd57b7406a.mp3"
  },
  {
    "id": "bf322df2096a46f18c579d0baa36f41d",
    "name": "Adrian",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/bf322df2096a46f18c579d0baa36f41d.mp3"
  },
  {
    "id": "b347db033a6549378b48d00acb0d06cd",
    "name": "Selene",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/b347db033a6549378b48d00acb0d06cd.mp3"
  },
  {
    "id": "536d3a5e000945adb7038665781a4aca",
    "name": "Ethan",
    "url": "https://pub-b995142090474379a930b856ab79b4d4.r2.dev/audio/best-practices-emotion-control/536d3a5e000945adb7038665781a4aca.mp3"
  }
]}
/>

## Overview

Control how your AI voice expresses emotions, from happy and excited to sad and contemplative. Add natural pauses, laughter, and other human-like elements to make speech more engaging.

<Tip>
  The `(parenthesis)` syntax on this page applies to the S1 model. S2 uses `[bracket]` syntax with natural language descriptions and is not limited to a fixed set of tags. See the [Models Overview](/developer-guide/models-pricing/models-overview#s2-natural-language-control) for details.
</Tip>

## How to Use

Simply wrap emotion tags in parentheses before your text:

```
(happy) What a beautiful day!
(sad) I'm sorry to hear that.
(excited) This is amazing news!
```

Include tone markers or audio effects:

```
(whispering) Let me tell you something.
(laughing) Ha ha ha, wow that's so funny!
```

## Important Rules

### Placement Matters

**For all languages:**

* Emotion tags MUST go at the beginning of sentences
* Tone controls can go anywhere in the text
* Sound effects can go anywhere in the text

**Correct:**

```
(happy) What a wonderful day!
```

**Incorrect:**

```
What a (happy) wonderful day!
```

## Best Practices

**Do:**

* Use one emotion per sentence
* Add sounds after relevant words
* Keep tags simple and clear
* Test different combinations

**Don't:**

* Overuse tags in short text
* Mix conflicting emotions
* Create custom tags
* Forget the parentheses

## Available Emotions

See the [Emotion Reference](/api-reference/emotion-reference) for the full list of supported emotions.

## Scene Examples

**Customer Service:**

```
(friendly) Hello! How can I help you today?
(empathetic) I understand your frustration.
(confident) I'll resolve this for you right away.
```

**Storytelling:**

```
(mysterious)(whispering) Once upon a midnight dreary...
(excited) Suddenly, the door burst open!
(scared)(shouting) Run for your lives!
```

**Educational Content:**

```
(enthusiastic) Welcome to today's lesson!
(curious) Have you ever wondered why the sky is blue?
(proud) Great job! You got it right!
```

## Real-World Examples

### Virtual Assistant

```
(friendly) Good morning! 
(helpful) I've prepared your schedule for today.
(concerned) You have three urgent emails.
(encouraging) Let's tackle them together!
```

### Audiobook Narration

```
(narrator) Chapter One: The Beginning
(mysterious) The old house stood silent in the fog.
(scared)(whispering) "Is anyone there?" she asked.
(relieved)(sighing) No one answered. Phew.
```

### Game Character

```
(brave) I'll defeat the dragon!
(struggling)(panting) This is... harder than... I thought!
(triumphant)(shouting) Victory is mine!
(laughing) Ha ha ha!
```

## Advanced Techniques

### Emotion Transitions

Gradually change emotions:

```
(happy) I got the promotion!
(uncertain) But... it means moving away.
(sad) I'll miss everyone here.
```

### Background Effects

Add atmosphere:

```
The comedy show was amazing (audience laughing)
Everyone was having fun (background laughter)
The crowd loved it (crowd laughing)
```

## Troubleshooting

### Emotion Not Working?

1. Check tag placement (beginning of sentence for emotions)
2. Verify spelling exactly matches the list
3. Don't use quotes around tags
4. Include parentheses

### Unnatural Sound?

* Add appropriate text after sound tags
* Don't overuse in short sentences
* Space out emotional changes
* Test with different voices

### Tips for Success

1. **Start simple** - Use basic emotions first
2. **Preview often** - Test how it sounds
3. **Be consistent** - Keep character emotions logical
4. **Less is more** - Don't overuse tags

## Get Creative

Experiment with combinations to create unique character voices and engaging narratives. The key is finding the right balance between emotional expression and natural speech flow.

## Support

Need help with emotions?

* **Try it live:** [fish.audio](https://fish.audio)
* **Community:** [Discord](https://discord.gg/fish-audio)
* **Email:** [support@fish.audio](mailto:support@fish.audio)


Built with [Mintlify](https://mintlify.com).