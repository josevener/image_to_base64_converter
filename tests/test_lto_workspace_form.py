"""The everyday workspace must be usable without technical import/setup screens."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from pages.lto_workspace import LtoWorkspacePage
from services.lto_workflow_service import LtoWorkflowService


class WorkspaceFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_editable_defaults_and_optional_advanced_tools(self) -> None:
        with TemporaryDirectory() as directory:
            service = LtoWorkflowService(Path(directory)/'registry.db','test-admin')
            service.ensure_starter_defaults()
            page = LtoWorkspacePage()
            page.render(service.summary(),[],[],[],[],[])
            self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count()) if page.tabs.isTabVisible(i)],
                             ['Transactions','Records','Defaults'])
            self.assertEqual(page.quick_office['tin'].text(),'000865491001')
            self.assertEqual(page.quick_years.value(),3)
            self.assertEqual(page.quick_fee_table.rowCount(),6)
            events=[]
            page.action_requested.connect(lambda action,data: events.append((action,data)))
            page.quick_office['name'].setText('EDITED OFFICE')
            page.quick_fee_table.item(0,1).setText('121.00')
            page.save_quick.click()
            self.assertEqual(events[-1][0],'save_quick_defaults')
            self.assertEqual(events[-1][1]['office']['name'],'EDITED OFFICE')
            self.assertEqual(events[-1][1]['fees']['initial'][0]['amount'],'121.00')
            page.advanced_toggle.setChecked(True)
            self.assertTrue(page.tabs.isTabVisible(3))
            self.assertTrue(page.tabs.isTabVisible(4))
            page.close()
            page.deleteLater()
            self.app.processEvents()
