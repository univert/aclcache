
// winappView.cpp : implementation of the CwinappView class
//

#include "pch.h"
#include "framework.h"
// SHARED_HANDLERS can be defined in an ATL project implementing preview, thumbnail
// and search filter handlers and allows sharing of document code with that project.
#ifndef SHARED_HANDLERS
#include "winapp.h"
#endif

#include "winappDoc.h"
#include "winappView.h"

#ifdef _DEBUG
#define new DEBUG_NEW
#endif


// CwinappView

IMPLEMENT_DYNCREATE(CwinappView, CView)

BEGIN_MESSAGE_MAP(CwinappView, CView)
	// Standard printing commands
	ON_COMMAND(ID_FILE_PRINT, &CView::OnFilePrint)
	ON_COMMAND(ID_FILE_PRINT_DIRECT, &CView::OnFilePrint)
	ON_COMMAND(ID_FILE_PRINT_PREVIEW, &CwinappView::OnFilePrintPreview)
	ON_WM_CONTEXTMENU()
	ON_WM_RBUTTONUP()
END_MESSAGE_MAP()

// CwinappView construction/destruction

CwinappView::CwinappView() noexcept
{
	// TODO: add construction code here

}

CwinappView::~CwinappView()
{
}

BOOL CwinappView::PreCreateWindow(CREATESTRUCT& cs)
{
	// TODO: Modify the Window class or styles here by modifying
	//  the CREATESTRUCT cs

	return CView::PreCreateWindow(cs);
}

// CwinappView drawing

void CwinappView::OnDraw(CDC* /*pDC*/)
{
	CwinappDoc* pDoc = GetDocument();
	ASSERT_VALID(pDoc);
	if (!pDoc)
		return;

	// TODO: add draw code for native data here
}


// CwinappView printing


void CwinappView::OnFilePrintPreview()
{
#ifndef SHARED_HANDLERS
	AFXPrintPreview(this);
#endif
}

BOOL CwinappView::OnPreparePrinting(CPrintInfo* pInfo)
{
	// default preparation
	return DoPreparePrinting(pInfo);
}

void CwinappView::OnBeginPrinting(CDC* /*pDC*/, CPrintInfo* /*pInfo*/)
{
	// TODO: add extra initialization before printing
}

void CwinappView::OnEndPrinting(CDC* /*pDC*/, CPrintInfo* /*pInfo*/)
{
	// TODO: add cleanup after printing
}

void CwinappView::OnRButtonUp(UINT /* nFlags */, CPoint point)
{
	ClientToScreen(&point);
	OnContextMenu(this, point);
}

void CwinappView::OnContextMenu(CWnd* /* pWnd */, CPoint point)
{
#ifndef SHARED_HANDLERS
	theApp.GetContextMenuManager()->ShowPopupMenu(IDR_POPUP_EDIT, point.x, point.y, this, TRUE);
#endif
}


// CwinappView diagnostics

#ifdef _DEBUG
void CwinappView::AssertValid() const
{
	CView::AssertValid();
}

void CwinappView::Dump(CDumpContext& dc) const
{
	CView::Dump(dc);
}

CwinappDoc* CwinappView::GetDocument() const // non-debug version is inline
{
	ASSERT(m_pDocument->IsKindOf(RUNTIME_CLASS(CwinappDoc)));
	return (CwinappDoc*)m_pDocument;
}
#endif //_DEBUG


// CwinappView message handlers
