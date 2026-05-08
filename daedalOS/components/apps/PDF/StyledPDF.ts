import styled from "styled-components";
import Message from "styles/common/Message";
import ScrollBars from "styles/common/ScrollBars";

export const StyledPdfShell = styled.div`
  contain: strict;
  display: flex;
  flex-direction: row;
  position: relative;
  text-align: center;
  top: 40px;

  && {
    height: ${({ theme }) =>
      `calc(100% - ${theme.sizes.titleBar.height}px - 40px)`};
  }
`;

export const StyledPdfThumbnailAside = styled.aside`
  ${ScrollBars()};

  background-color: rgb(40 44 47);
  border-right: 1px solid rgb(28 30 32);
  box-sizing: border-box;
  flex-shrink: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 8px 6px;
  width: 112px;

  button.thumb-button {
    background: rgb(50 54 57);
    border: 2px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    display: block;
    margin: 0 auto 8px;
    padding: 2px;
    width: 100%;

    &.active {
      border-color: rgb(138 180 248);
    }

    &:hover {
      background: rgb(58 62 65);
    }

    canvas {
      display: block;
      height: auto;
      margin: 0 auto;
      max-width: 100%;
    }
  }
`;

export const StyledPdfScrollArea = styled.div`
  ${ScrollBars()};

  contain: strict;
  flex: 1;
  min-width: 0;
  overflow: auto;
  position: relative;
  text-align: center;

  canvas {
    box-shadow: 0 0 5px hsl(0 0% 10% / 50%);
  }

  &.drop {
    ${Message("Drop PDF file here", "#fff")};
  }
`;
