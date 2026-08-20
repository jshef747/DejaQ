"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

export type ComboboxOption = { value: string; label: string };
export type ComboboxGroup = { label?: string; options: ComboboxOption[] };

interface ComboboxProps {
  groups: ComboboxGroup[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  /** true = editable text input that filters as you type (the caller re-filters `groups`); false = button-only, native-<select>-style listbox with typeahead. */
  filterable?: boolean;
  emptyText?: string;
}

type FlatEntry = { option: ComboboxOption; groupIndex: number };

function flatten(groups: ComboboxGroup[]): FlatEntry[] {
  const flat: FlatEntry[] = [];
  groups.forEach((g, groupIndex) => g.options.forEach((option) => flat.push({ option, groupIndex })));
  return flat;
}

export default function Combobox({
  groups,
  value,
  onChange,
  placeholder,
  disabled,
  filterable = false,
  emptyText = "No matches",
}: ComboboxProps) {
  const baseId = useId();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const typeaheadRef = useRef({ text: "", timer: 0 as ReturnType<typeof setTimeout> | 0 });
  const suppressScrollCloseRef = useRef(false);

  const flat = useMemo(() => flatten(groups), [groups]);
  const selectedLabel = useMemo(
    () => flat.find((f) => f.option.value === value)?.option.label ?? "",
    [flat, value],
  );

  function close(refocus: boolean) {
    setOpen(false);
    setActiveIndex(-1);
    if (refocus) (filterable ? inputRef.current : buttonRef.current)?.focus();
  }

  function openList(initialActive?: number) {
    if (disabled) return;
    setOpen(true);
    if (typeof initialActive === "number") {
      setActiveIndex(flat.length > 0 ? initialActive : -1);
    } else if (!filterable) {
      const idx = flat.findIndex((f) => f.option.value === value);
      setActiveIndex(idx >= 0 ? idx : flat.length > 0 ? 0 : -1);
    } else {
      setActiveIndex(flat.length > 0 ? 0 : -1);
    }
  }

  function commit(index: number) {
    const item = flat[index];
    if (!item) return;
    onChange(item.option.value);
    close(true);
  }

  useEffect(() => {
    if (!open) return;
    function onDocPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close(false);
    }
    function onScroll(e: Event) {
      // Our own scrollIntoView (keeping the active option in view) fires a
      // scroll event too; ignore anything inside the popup so keyboard
      // navigation past the fold doesn't close the list on itself.
      if (suppressScrollCloseRef.current) return;
      if (listRef.current && listRef.current.contains(e.target as Node)) return;
      close(false);
    }
    document.addEventListener("pointerdown", onDocPointerDown, true);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("pointerdown", onDocPointerDown, true);
      window.removeEventListener("scroll", onScroll, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    suppressScrollCloseRef.current = true;
    listRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" });
    const t = setTimeout(() => {
      suppressScrollCloseRef.current = false;
    }, 50);
    return () => clearTimeout(t);
  }, [open, activeIndex]);

  // `groups` (and so `flat`) can shrink out from under us - e.g. the caller
  // re-filters a filterable list on every keystroke - which would otherwise
  // leave activeIndex pointing past the end of the new, shorter array.
  useEffect(() => {
    if (activeIndex >= flat.length) setActiveIndex(flat.length > 0 ? flat.length - 1 : -1);
  }, [flat, activeIndex]);

  function typeahead(char: string) {
    const buf = (typeaheadRef.current.text + char).toLowerCase();
    typeaheadRef.current.text = buf;
    clearTimeout(typeaheadRef.current.timer);
    typeaheadRef.current.timer = setTimeout(() => {
      typeaheadRef.current.text = "";
    }, 600);
    const n = flat.length;
    if (n === 0) return;
    const startFrom = activeIndex >= 0 ? activeIndex + 1 : 0;
    for (let i = 0; i < n; i++) {
      const idx = (startFrom + i) % n;
      if (flat[idx].option.label.toLowerCase().startsWith(buf)) {
        setActiveIndex(idx);
        if (!open) setOpen(true);
        return;
      }
    }
  }

  function onRootBlur(e: React.FocusEvent) {
    const next = e.relatedTarget as Node | null;
    if (rootRef.current && next && rootRef.current.contains(next)) return;
    if (open) close(false);
  }

  function onButtonKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList();
        else setActiveIndex((i) => Math.min(flat.length - 1, i + 1));
        return;
      case "ArrowUp":
        e.preventDefault();
        if (!open) openList();
        else setActiveIndex((i) => Math.max(0, i - 1));
        return;
      case "Home":
        if (open) {
          e.preventDefault();
          setActiveIndex(0);
        }
        return;
      case "End":
        if (open) {
          e.preventDefault();
          setActiveIndex(flat.length - 1);
        }
        return;
      case "Enter":
      case " ":
        e.preventDefault();
        if (!open) openList();
        else if (activeIndex >= 0) commit(activeIndex);
        return;
      case "Escape":
        if (open) {
          e.preventDefault();
          close(true);
        }
        return;
      default:
        if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          typeahead(e.key);
        }
    }
  }

  function onInputKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList();
        else setActiveIndex((i) => (i + 1 >= flat.length ? 0 : i + 1));
        return;
      case "ArrowUp":
        e.preventDefault();
        if (!open) openList();
        else setActiveIndex((i) => (i - 1 < 0 ? flat.length - 1 : i - 1));
        return;
      case "Enter":
        if (open && activeIndex >= 0) {
          e.preventDefault();
          commit(activeIndex);
        }
        return;
      case "Escape":
        if (open) {
          e.preventDefault();
          close(false);
        }
        return;
    }
  }

  const listboxId = `${baseId}-listbox`;
  const activeItem = activeIndex >= 0 ? flat[activeIndex] : undefined;
  const activeOptionId = activeItem ? `${baseId}-opt-${activeItem.option.value}` : undefined;

  return (
    <div className="ds-combo" ref={rootRef} onBlur={onRootBlur}>
      {filterable ? (
        <input
          ref={inputRef}
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={open ? activeOptionId : undefined}
          className="ds-input ds-input-sans"
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          onChange={(e) => {
            onChange(e.target.value);
            openList(0);
          }}
          onFocus={() => openList()}
          onKeyDown={onInputKeyDown}
        />
      ) : (
        <button
          ref={buttonRef}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-haspopup="listbox"
          aria-activedescendant={open ? activeOptionId : undefined}
          disabled={disabled}
          className="ds-select ds-combo-trigger"
          onClick={() => (open ? close(true) : openList())}
          onKeyDown={onButtonKeyDown}
        >
          <span className={selectedLabel ? "ds-combo-value" : "ds-combo-placeholder"}>
            {selectedLabel || placeholder}
          </span>
          <ChevronDown size={14} className="ds-combo-chevron" />
        </button>
      )}

      {open && (
        <div ref={listRef} id={listboxId} role="listbox" aria-label={placeholder} className="ds-combo-popup">
          {flat.length === 0 && <div className="ds-combo-empty">{emptyText}</div>}
          {groups.map((group, groupIndex) => {
            if (group.options.length === 0) return null;
            const headingId = `${baseId}-group-${groupIndex}`;
            return (
              <div role="group" aria-labelledby={group.label ? headingId : undefined} key={groupIndex}>
                {group.label && (
                  <div id={headingId} role="presentation" className="ds-combo-group-label">
                    {group.label}
                  </div>
                )}
                {group.options.map((opt) => {
                  const flatIndex = flat.findIndex((f) => f.option === opt);
                  const active = flatIndex === activeIndex;
                  const selected = opt.value === value;
                  return (
                    <div
                      key={opt.value}
                      id={`${baseId}-opt-${opt.value}`}
                      role="option"
                      aria-selected={selected}
                      data-index={flatIndex}
                      className={`ds-combo-option${active ? " ds-combo-option-active" : ""}${selected ? " ds-combo-option-selected" : ""}`}
                      // onMouseMove (not onMouseEnter): keyboard nav scrolls the
                      // list under a stationary cursor, which still fires
                      // enter/over on the element that ends up underneath it and
                      // would otherwise hijack the keyboard-selected option.
                      onMouseMove={() => setActiveIndex(flatIndex)}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => commit(flatIndex)}
                    >
                      <span>{opt.label}</span>
                      {selected && <Check size={13} className="ds-combo-check" />}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
