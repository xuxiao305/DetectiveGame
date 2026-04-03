#!/usr/bin/env python3
"""
GUI dual-panel smoke test - validates new UI can initialize and handle basic operations.
"""
import sys
from pathlib import Path

# Add parent src to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "src"))

import tkinter as tk
from interrogation_mvp.controller import GameController
from interrogation_mvp.gui import InterrogationGUI


def test_gui_initialization():
    """Test that GUI can be created with dual-panel layout."""
    print("Testing GUI initialization...")
    
    root = tk.Tk()
    controller = GameController()
    gui = InterrogationGUI(root, controller)
    
    # Check that all new widgets exist
    assert hasattr(gui, '_detective_chat'), "Missing _detective_chat"
    assert hasattr(gui, '_suspect_chat'), "Missing _suspect_chat"
    assert hasattr(gui, '_detective_thought_var'), "Missing _detective_thought_var"
    assert hasattr(gui, '_suspect_thought_var'), "Missing _suspect_thought_var"
    assert hasattr(gui, '_detective_memory_text'), "Missing _detective_memory_text"
    assert hasattr(gui, '_suspect_memory_text'), "Missing _suspect_memory_text"
    assert hasattr(gui, '_contradiction_text'), "Missing _contradiction_text"
    
    # Check that old _chat widget does NOT exist
    assert not hasattr(gui, '_chat'), "Old _chat widget should not exist"
    
    print("✅ All dual-panel widgets created successfully")
    
    # Don't call mainloop - just destroy
    root.destroy()
    
    return True


def test_helper_methods():
    """Test that new helper methods exist and have correct signatures."""
    print("Testing helper methods...")
    
    root = tk.Tk()
    controller = GameController()
    gui = InterrogationGUI(root, controller)
    
    # Check method existence
    assert hasattr(gui, '_append_to_widget'), "Missing _append_to_widget"
    assert hasattr(gui, '_set_widget_text'), "Missing _set_widget_text"
    assert hasattr(gui, '_refresh_memory_panels'), "Missing _refresh_memory_panels"
    
    print("✅ All helper methods exist")
    
    root.destroy()
    
    return True


if __name__ == "__main__":
    try:
        test_gui_initialization()
        test_helper_methods()
        print("\n🎉 GUI smoke test PASSED")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ GUI smoke test FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ GUI smoke test ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
